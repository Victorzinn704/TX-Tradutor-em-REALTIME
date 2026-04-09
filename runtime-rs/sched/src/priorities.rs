/// Prioridade de um segmento de áudio no scheduler.
///
/// `Final` sempre tem prioridade absoluta sobre `Partial`.
/// Isso garante que um resultado parcial nunca bloqueia uma
/// transcrição final de entrar no pipeline de ASR.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Priority {
    Partial = 0,
    Final   = 1,
}

impl Priority {
    pub fn is_final(self) -> bool {
        matches!(self, Priority::Final)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn final_greater_than_partial() {
        assert!(Priority::Final > Priority::Partial);
    }
}
