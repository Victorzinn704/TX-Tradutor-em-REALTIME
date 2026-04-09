use webrtc_vad::{SampleRate, Vad, VadMode};

const VALID_FRAME_SIZES: [usize; 3] = [160, 320, 480];

pub struct Vad1 {
    vad: Vad,
}

impl Vad1 {
    /// `aggressiveness`: 0 (menos agressivo) a 3 (mais agressivo)
    pub fn new(aggressiveness: u8) -> Self {
        let mode = match aggressiveness.min(3) {
            0 => VadMode::Quality,
            1 => VadMode::LowBitrate,
            2 => VadMode::Aggressive,
            _ => VadMode::VeryAggressive,
        };

        Self {
            vad: Vad::new_with_rate_and_mode(SampleRate::Rate16kHz, mode),
        }
    }

    /// Retorna `true` se o frame contém fala detectada.
    /// `frame_16k` deve ter 160, 320 ou 480 amostras (10/20/30ms @ 16kHz).
    pub fn is_speech(&mut self, frame_16k: &[f32]) -> bool {
        if !VALID_FRAME_SIZES.contains(&frame_16k.len()) {
            return false;
        }

        let frame: Vec<i16> = frame_16k
            .iter()
            .copied()
            .map(|sample| {
                let sample = if sample.is_finite() {
                    sample.clamp(-1.0, 1.0)
                } else {
                    0.0
                };
                (sample * i16::MAX as f32).round() as i16
            })
            .collect();

        matches!(self.vad.is_voice_segment(&frame), Ok(true))
    }
}

impl Default for Vad1 {
    fn default() -> Self {
        Self::new(2)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_invalid_frame_sizes() {
        let mut vad = Vad1::default();
        assert!(!vad.is_speech(&[0.0; 159]));
        assert!(!vad.is_speech(&[0.0; 161]));
    }

    #[test]
    fn silence_is_not_speech() {
        let mut vad = Vad1::default();
        assert!(!vad.is_speech(&[0.0; 160]));
    }
}
