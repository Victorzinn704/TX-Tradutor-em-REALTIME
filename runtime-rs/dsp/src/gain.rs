/// Aplica ganho de pico com cap máximo e threshold mínimo.
///
/// - Se `peak <= 0.0` → noop (silêncio total).
/// - Se `gain < 1.05` → noop (já está suficientemente alto, evita micro-oscilação).
/// - Resultado clamped em [-1.0, 1.0] para evitar clipping hard.
pub fn apply_gain(samples: &mut [f32], target_peak: f32, gain_cap: f32) {
    let peak = samples
        .iter()
        .copied()
        .fold(0.0f32, |acc, s| acc.max(s.abs()));

    if peak <= 0.0 {
        return;
    }

    let gain = (target_peak / peak).min(gain_cap);
    if gain > 1.05 {
        for s in samples.iter_mut() {
            *s = (*s * gain).clamp(-1.0, 1.0);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn boosts_low_signal() {
        let mut samples = vec![0.1f32, -0.1, 0.05];
        apply_gain(&mut samples, 0.88, 4.0);
        assert!(samples[0] > 0.1, "deveria amplificar");
    }

    #[test]
    fn does_not_boost_loud_signal() {
        let mut samples = vec![0.9f32, -0.9];
        let before = samples.clone();
        apply_gain(&mut samples, 0.88, 4.0);
        // gain = 0.88/0.9 ≈ 0.977 < 1.05 → noop
        assert_eq!(samples, before);
    }

    #[test]
    fn clamps_to_unit_range() {
        let mut samples = vec![0.01f32];
        // target_peak=1.0, gain_cap=200.0 → gain=100 → 0.01*100=1.0 → clamp ok
        apply_gain(&mut samples, 1.0, 200.0);
        assert!(samples[0] <= 1.0 && samples[0] >= -1.0);
    }

    #[test]
    fn silence_noop() {
        let mut samples = vec![0.0f32; 16];
        apply_gain(&mut samples, 0.88, 4.0);
        assert!(samples.iter().all(|&s| s == 0.0));
    }
}
