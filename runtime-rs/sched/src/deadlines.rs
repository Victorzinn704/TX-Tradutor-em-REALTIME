use std::time::{Duration, Instant};

/// Deadline por segmento.
///
/// Criado no momento em que o segmento entra na fila.
/// `is_expired()` descarta silenciosamente dados velhos antes de enviá-los
/// ao ASR — dado velho deve morrer, não bloquear fila nova.
#[derive(Debug, Clone)]
pub struct Deadline {
    created_at: Instant,
    ttl:        Duration,
}

impl Deadline {
    pub fn new(ttl: Duration) -> Self {
        Self { created_at: Instant::now(), ttl }
    }

    /// `true` se o segmento está fora do SLA e deve ser descartado.
    pub fn is_expired(&self) -> bool {
        self.created_at.elapsed() > self.ttl
    }

    /// Idade em milissegundos desde a criação.
    pub fn age_ms(&self) -> u64 {
        self.created_at.elapsed().as_millis() as u64
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn not_expired_immediately() {
        let d = Deadline::new(Duration::from_secs(10));
        assert!(!d.is_expired());
    }

    #[test]
    fn expired_after_ttl() {
        let d = Deadline::new(Duration::from_millis(1));
        std::thread::sleep(Duration::from_millis(5));
        assert!(d.is_expired());
    }
}
