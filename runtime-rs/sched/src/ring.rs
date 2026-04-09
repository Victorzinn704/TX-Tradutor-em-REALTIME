/// Wrapper fino sobre `rtrb` para semântica de áudio.
///
/// rtrb é SPSC lock-free com alocação fixa na criação.
/// O callback de áudio (Producer) nunca aloca — único requisito realtime.
///
/// Uma instância por fonte: mic usa um par, sistema usa outro.
/// Isso elimina contenção e mantém os canais completamente independentes.
pub use rtrb::{Consumer, Producer, RingBuffer};

/// Cria um par `(Producer<f32>, Consumer<f32>)` para uma fonte de áudio.
///
/// `capacity_frames`: quantos f32 cabem no buffer (ex: 48_000 * 2 = 2s @ 48kHz).
/// Alocação ocorre apenas aqui — nunca no callback realtime.
pub fn audio_ring(capacity_frames: usize) -> (Producer<f32>, Consumer<f32>) {
    RingBuffer::new(capacity_frames)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn producer_consumer_roundtrip() {
        let (mut prod, mut cons) = audio_ring(64);
        prod.push(0.5f32).unwrap();
        prod.push(-0.5f32).unwrap();
        assert_eq!(cons.pop().unwrap(), 0.5);
        assert_eq!(cons.pop().unwrap(), -0.5);
    }

    #[test]
    fn full_buffer_returns_error() {
        let (mut prod, _cons) = audio_ring(2);
        prod.push(1.0f32).unwrap();
        prod.push(1.0f32).unwrap();
        assert!(prod.push(1.0f32).is_err()); // backpressure explícita
    }
}
