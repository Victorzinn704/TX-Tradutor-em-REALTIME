/// Trait de captura de áudio — implementado pelo Codex para WASAPI.
///
/// O contrato é simples: `start()` começa a chamar `callback` com
/// chunks de f32 brutos (pode ser multi-canal, taxa original).
/// O caller (ffi ou sched) faz DSP depois.
pub mod clock;
pub mod device_enum;
pub mod loopback_capture;
pub mod wasapi_capture;

pub use clock::now_ms;
pub use device_enum::{enumerate_devices, find_by_name, find_default_mic, find_loopback, DeviceInfo};
pub use loopback_capture::LoopbackCapture;
pub use wasapi_capture::MicCapture;

use thiserror::Error;

#[derive(Debug, Error)]
pub enum CaptureError {
    #[error("dispositivo não encontrado: {0}")]
    DeviceNotFound(String),
    #[error("formato de áudio não suportado: {0}")]
    FormatUnsupported(String),
    #[error("falha ao abrir stream: {0}")]
    StreamOpen(String),
    #[error("erro WASAPI: {0}")]
    Wasapi(String),
}

/// Callback chamado pelo thread de captura com samples brutos.
/// DEVE ser lock-free — não pode bloquear.
pub type AudioCallback = Box<dyn Fn(&[f32], u32, u16) + Send + 'static>;
//                                       ^     ^    ^
//                               samples |     |    channels
//                               sample_rate --'

/// Interface comum para MicCapture e LoopbackCapture.
pub trait AudioCapture: Send {
    fn source_id(&self) -> &str;
    fn sample_rate(&self) -> u32;
    fn channels(&self) -> u16;
    fn start(&mut self, callback: AudioCallback) -> Result<(), CaptureError>;
    fn stop(&mut self);
}

#[cfg(test)]
mod tests {
    use super::*;
    use rtxlator_dsp::{Segmenter, Vad1};

    const FRAME_SIZE: usize = 480;

    fn sine_frame(freq_hz: f32, amplitude: f32) -> Vec<f32> {
        (0..FRAME_SIZE)
            .map(|index| {
                let time = index as f32 / 16_000.0;
                (std::f32::consts::TAU * freq_hz * time).sin() * amplitude
            })
            .collect()
    }

    fn synthesize_speech_frame() -> Vec<f32> {
        let amplitudes = [0.35_f32, 0.5, 0.65, 0.8];
        let fundamentals = [90.0_f32, 120.0, 150.0, 180.0, 210.0, 240.0];

        for amplitude in amplitudes {
            for fundamental_hz in fundamentals {
                let candidate: Vec<f32> = (0..FRAME_SIZE)
                    .map(|index| {
                        let time = index as f32 / 16_000.0;
                        let fundamental =
                            (std::f32::consts::TAU * fundamental_hz * time).sin() * amplitude;
                        let harmonic_2 =
                            (std::f32::consts::TAU * (fundamental_hz * 2.0) * time).sin()
                                * amplitude
                                * 0.45;
                        let harmonic_3 =
                            (std::f32::consts::TAU * (fundamental_hz * 3.0) * time).sin()
                                * amplitude
                                * 0.25;
                        let envelope =
                            (std::f32::consts::TAU * 3.0 * time).sin().abs().mul_add(0.35, 0.65);
                        ((fundamental + harmonic_2 + harmonic_3) * envelope).clamp(-1.0, 1.0)
                    })
                    .collect();

                let mut vad = Vad1::default();
                if vad.is_speech(&candidate) {
                    return candidate;
                }
            }
        }

        for frequency_hz in [180.0_f32, 220.0, 260.0, 300.0] {
            let candidate = sine_frame(frequency_hz, 0.95);
            let mut vad = Vad1::default();
            if vad.is_speech(&candidate) {
                return candidate;
            }
        }

        panic!("unable to synthesize a frame accepted by WebRTC VAD");
    }

    #[test]
    fn now_ms_returns_value_greater_than_zero() {
        assert!(now_ms() > 0);
    }

    #[test]
    fn enumerate_devices_does_not_panic() {
        let result = std::panic::catch_unwind(enumerate_devices);
        assert!(result.is_ok(), "enumerate_devices() should never panic");
    }

    #[test]
    fn capture_error_formats_helpfully() {
        let error = CaptureError::DeviceNotFound("usb mic".to_string());
        assert_eq!(error.to_string(), "dispositivo não encontrado: usb mic");
    }

    #[test]
    fn vad_rejects_silence() {
        let mut vad = Vad1::default();
        assert!(!vad.is_speech(&[0.0; FRAME_SIZE]));
    }

    #[test]
    fn vad_rejects_wrong_frame_size() {
        let mut vad = Vad1::default();
        assert!(!vad.is_speech(&[0.0; FRAME_SIZE - 1]));
    }

    #[test]
    fn segmenter_flush_returns_none_when_buffer_is_empty() {
        let mut segmenter = Segmenter::new(2, FRAME_SIZE);
        assert_eq!(segmenter.flush(), None);
    }

    #[test]
    fn segmenter_emits_after_silence_threshold() {
        let speech = synthesize_speech_frame();
        let silence = [0.0; FRAME_SIZE];
        let mut segmenter = Segmenter::new(1, FRAME_SIZE);

        assert_eq!(segmenter.feed(&speech), None);

        for _ in 0..10 {
            if let Some(emitted) = segmenter.feed(&silence) {
                assert!(emitted.len() >= FRAME_SIZE);
                return;
            }
        }

        panic!("segment should emit once sustained silence reaches the threshold");
    }
}
