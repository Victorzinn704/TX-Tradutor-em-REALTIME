use rubato::{
    Resampler, SincFixedIn, SincInterpolationParameters, SincInterpolationType, WindowFunction,
};
use thiserror::Error;

/// Taxa alvo exigida pelo Whisper.
pub const TARGET_SR: u32 = 16_000;

#[derive(Debug, Error)]
pub enum ResampleError {
    #[error("falha ao criar resampler ({src_sr} -> {TARGET_SR}Hz): {msg}")]
    Construction { src_sr: u32, msg: String },
    #[error("falha ao processar resampling: {0}")]
    Processing(String),
}

/// Converte `input` de `source_sr` Hz para 16 kHz (mono, f32).
///
/// - Se `source_sr == TARGET_SR`, retorna clone sem processamento.
/// - Usa SincFixedIn com BlackmanHarris2 — melhor tradeoff qualidade/velocidade
///   para chunks de áudio de fala (~100–3000ms).
pub fn resample_to_16k(input: &[f32], source_sr: u32) -> Result<Vec<f32>, ResampleError> {
    if source_sr == TARGET_SR || input.is_empty() {
        return Ok(input.to_vec());
    }

    let ratio = TARGET_SR as f64 / source_sr as f64;

    let params = SincInterpolationParameters {
        sinc_len: 64,
        f_cutoff: 0.95,
        interpolation: SincInterpolationType::Linear,
        oversampling_factor: 64,
        window: WindowFunction::BlackmanHarris2,
    };

    let mut resampler = SincFixedIn::<f32>::new(ratio, 2.0, params, input.len(), 1)
        .map_err(|e| ResampleError::Construction {
            src_sr: source_sr,
            msg: e.to_string(),
        })?;

    let waves_in = vec![input.to_vec()];
    let mut waves_out = resampler
        .process(&waves_in, None)
        .map_err(|e| ResampleError::Processing(e.to_string()))?;

    Ok(waves_out.remove(0))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn passthrough_at_16k() {
        let input: Vec<f32> = (0..160).map(|i| i as f32 * 0.001).collect();
        let out = resample_to_16k(&input, 16_000).unwrap();
        assert_eq!(out, input);
    }

    #[test]
    fn downsamples_48k_to_16k() {
        let input = vec![0.0f32; 4_800]; // 100ms @ 48kHz
        let out = resample_to_16k(&input, 48_000).unwrap();
        let expected = (4_800.0f64 * 16_000.0 / 48_000.0).round() as usize;
        let diff = (out.len() as i64 - expected as i64).unsigned_abs() as usize;
        assert!(diff <= 16, "saída={} esperado~{}", out.len(), expected);
    }

    #[test]
    fn empty_input_returns_empty() {
        let out = resample_to_16k(&[], 48_000).unwrap();
        assert!(out.is_empty());
    }
}
