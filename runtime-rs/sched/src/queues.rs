use std::time::Duration;

use tracing::debug;

use crate::{Deadline, Priority};

/// Um segmento de áudio pronto para ASR, com metadados de scheduling.
#[derive(Debug)]
pub struct SegmentEntry {
    pub source_id: String,
    pub samples:   Vec<f32>,
    pub priority:  Priority,
    pub deadline:  Deadline,
}

impl SegmentEntry {
    pub fn new_partial(source_id: impl Into<String>, samples: Vec<f32>, ttl: Duration) -> Self {
        Self {
            source_id: source_id.into(),
            samples,
            priority: Priority::Partial,
            deadline: Deadline::new(ttl),
        }
    }

    pub fn new_final(source_id: impl Into<String>, samples: Vec<f32>, ttl: Duration) -> Self {
        Self {
            source_id: source_id.into(),
            samples,
            priority: Priority::Final,
            deadline: Deadline::new(ttl),
        }
    }
}

/// Fila de segmentos com:
///  - Prioridade absoluta de `Final` sobre `Partial`
///  - Descarte por deadline (dado velho morre na pop, não bloqueia)
///  - Substituição de parcial por fonte (replace_partial)
///  - Capacidade bounded: oldest-drops quando cheio
///
/// Não é thread-safe por si só — envolva com Mutex se compartilhado.
pub struct SegmentQueue {
    capacity: usize,
    finals:   Vec<SegmentEntry>,
    partials: Vec<SegmentEntry>,
}

impl SegmentQueue {
    pub fn new(capacity: usize) -> Self {
        Self {
            capacity,
            finals:   Vec::with_capacity(capacity),
            partials: Vec::with_capacity(capacity),
        }
    }

    /// Insere um segmento. Retorna `false` se foi necessário descartar
    /// o mais antigo para abrir espaço (backpressure explícita).
    pub fn push(&mut self, entry: SegmentEntry) -> bool {
        let (queue, label) = match entry.priority {
            Priority::Final   => (&mut self.finals,   "final"),
            Priority::Partial => (&mut self.partials, "partial"),
        };

        if queue.len() >= self.capacity {
            debug!("sched: {} queue full, dropping oldest", label);
            queue.remove(0);
            queue.push(entry);
            return false; // sinalizou backpressure
        }

        queue.push(entry);
        true
    }

    /// Pop com prioridade: Final > Partial.
    /// Entradas com deadline expirado são descartadas antes de retornar.
    pub fn pop(&mut self) -> Option<SegmentEntry> {
        // Tenta servir um Final válido primeiro
        while let Some(entry) = self.finals.first() {
            if !entry.deadline.is_expired() {
                return Some(self.finals.remove(0));
            }
            let dropped = self.finals.remove(0);
            debug!("sched: expired final dropped (age={}ms)", dropped.deadline.age_ms());
        }

        // Drena Partials expirados e serve o primeiro válido
        self.partials.retain(|e| {
            if e.deadline.is_expired() {
                debug!("sched: expired partial dropped");
                false
            } else {
                true
            }
        });

        if self.partials.is_empty() {
            None
        } else {
            Some(self.partials.remove(0))
        }
    }

    /// Substitui o parcial mais recente da mesma fonte.
    /// Evita acúmulo de parciais stale quando o ASR está ocupado.
    pub fn replace_partial(&mut self, entry: SegmentEntry) {
        self.partials.retain(|e| e.source_id != entry.source_id);
        self.push(entry);
    }

    pub fn len(&self) -> usize {
        self.finals.len() + self.partials.len()
    }

    pub fn is_empty(&self) -> bool {
        self.finals.is_empty() && self.partials.is_empty()
    }

    /// Quantidade de finais pendentes.
    pub fn finals_pending(&self) -> usize {
        self.finals.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    const TTL: Duration = Duration::from_secs(10);

    #[test]
    fn final_has_priority_over_partial() {
        let mut q = SegmentQueue::new(8);
        q.push(SegmentEntry::new_partial("mic", vec![0.0; 16], TTL));
        q.push(SegmentEntry::new_final("mic", vec![1.0; 16], TTL));
        let e = q.pop().unwrap();
        assert!(e.priority.is_final());
    }

    #[test]
    fn partial_served_when_no_final() {
        let mut q = SegmentQueue::new(8);
        q.push(SegmentEntry::new_partial("mic", vec![0.5; 8], TTL));
        let e = q.pop().unwrap();
        assert_eq!(e.priority, Priority::Partial);
    }

    #[test]
    fn replace_partial_removes_old_same_source() {
        let mut q = SegmentQueue::new(8);
        q.push(SegmentEntry::new_partial("mic", vec![0.0; 8], TTL));
        q.replace_partial(SegmentEntry::new_partial("mic", vec![1.0; 8], TTL));
        assert_eq!(q.partials.len(), 1);
        assert_eq!(q.partials[0].samples[0], 1.0f32);
    }

    #[test]
    fn replace_partial_keeps_different_source() {
        let mut q = SegmentQueue::new(8);
        q.push(SegmentEntry::new_partial("mic",    vec![0.0; 8], TTL));
        q.push(SegmentEntry::new_partial("system", vec![0.5; 8], TTL));
        q.replace_partial(SegmentEntry::new_partial("mic", vec![1.0; 8], TTL));
        assert_eq!(q.partials.len(), 2);
    }

    #[test]
    fn expired_entry_is_dropped_on_pop() {
        let mut q = SegmentQueue::new(8);
        q.push(SegmentEntry::new_partial("mic", vec![0.0; 8], Duration::from_millis(1)));
        std::thread::sleep(Duration::from_millis(5));
        assert!(q.pop().is_none());
    }

    #[test]
    fn backpressure_returns_false_when_full() {
        let mut q = SegmentQueue::new(2);
        q.push(SegmentEntry::new_partial("mic", vec![], TTL));
        q.push(SegmentEntry::new_partial("mic", vec![], TTL));
        let accepted = q.push(SegmentEntry::new_partial("mic", vec![], TTL));
        assert!(!accepted);
        assert_eq!(q.partials.len(), 2); // cap mantido
    }

    #[test]
    fn empty_queue_returns_none() {
        let mut q = SegmentQueue::new(8);
        assert!(q.pop().is_none());
        assert!(q.is_empty());
    }
}
