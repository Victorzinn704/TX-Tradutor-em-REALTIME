use pyo3::prelude::*;

/// Segmento de áudio com VAD estágio 1 confirmado, pronto para ASR.
///
/// Esse é o contrato entre o runtime Rust e o Python.
/// Python recebe isso e chama `whisper_service.transcribe(segment)` diretamente.
///
/// Todos os campos são `#[pyo3(get)]` — read-only do lado Python,
/// evitando mutabilidade acidental no hot path.
#[pyclass]
#[derive(Debug, Clone)]
pub struct AudioSegment {
    /// "mic" | "system" | "system_en" — mapeia para source_kind no Python
    #[pyo3(get)]
    pub source_id: String,

    /// Amostras 16kHz mono f32 — já processadas pelo DSP Rust
    #[pyo3(get)]
    pub samples: Vec<f32>,

    /// Timestamp absoluto de captura em milissegundos (desde epoch)
    #[pyo3(get)]
    pub captured_at_ms: u64,

    /// RMS calculado no Rust — Python não precisa recalcular
    #[pyo3(get)]
    pub rms: f32,

    /// Sempre TARGET_SR (16_000) na saída do pipeline Rust
    #[pyo3(get)]
    pub sample_rate: u32,
}

#[pymethods]
impl AudioSegment {
    #[new]
    #[pyo3(signature = (source_id, samples, captured_at_ms, rms, sample_rate=16_000))]
    pub fn new(
        source_id: String,
        samples: Vec<f32>,
        captured_at_ms: u64,
        rms: f32,
        sample_rate: u32,
    ) -> Self {
        Self { source_id, samples, captured_at_ms, rms, sample_rate }
    }

    fn __repr__(&self) -> String {
        format!(
            "AudioSegment(source='{}', frames={}, rms={:.4}, at={}ms)",
            self.source_id,
            self.samples.len(),
            self.rms,
            self.captured_at_ms,
        )
    }

    /// Duração em milissegundos baseada no número de amostras.
    fn duration_ms(&self) -> f32 {
        if self.sample_rate == 0 {
            return 0.0;
        }
        (self.samples.len() as f32 / self.sample_rate as f32) * 1000.0
    }
}

/// Módulo Python: `import runtime_rs`
///
/// Uso no Python:
/// ```python
/// try:
///     from runtime_rs import AudioSegment
///     RUST_RUNTIME = True
/// except ImportError:
///     RUST_RUNTIME = False
/// ```
#[pymodule]
fn runtime_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<AudioSegment>()?;
    Ok(())
}
