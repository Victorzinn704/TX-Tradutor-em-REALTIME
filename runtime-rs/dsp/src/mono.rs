/// Converte buffer multi-canal para mono por média simples.
/// `channels == 1` retorna clone sem alocação extra.
pub fn to_mono(samples: &[f32], channels: usize) -> Vec<f32> {
    if channels <= 1 {
        return samples.to_vec();
    }
    let frames = samples.len() / channels;
    let inv    = 1.0 / channels as f32;
    let mut out = Vec::with_capacity(frames);
    for frame in 0..frames {
        let sum: f32 = (0..channels)
            .map(|c| samples[frame * channels + c])
            .sum();
        out.push(sum * inv);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stereo_averages_correctly() {
        // L=1.0, R=3.0  →  mono=2.0
        let stereo = vec![1.0f32, 3.0, 1.0, 3.0];
        assert_eq!(to_mono(&stereo, 2), vec![2.0, 2.0]);
    }

    #[test]
    fn mono_passthrough_no_copy_needed() {
        let input = vec![0.5f32, 0.8, -0.3];
        assert_eq!(to_mono(&input, 1), input);
    }

    #[test]
    fn empty_input_returns_empty() {
        assert!(to_mono(&[], 2).is_empty());
    }
}
