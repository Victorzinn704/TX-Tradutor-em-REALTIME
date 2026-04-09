use crate::vad_stage1::Vad1;

const FRAME_SIZE: usize = 480;

pub struct Segmenter {
    vad: Vad1,
    buffer: Vec<f32>,
    pending: Vec<f32>,
    silence_frames: usize,
    silence_run: usize,
    min_samples: usize,
}

impl Segmenter {
    pub fn new(silence_frames: usize, min_samples: usize) -> Self {
        Self {
            vad: Vad1::default(),
            buffer: Vec::new(),
            pending: Vec::new(),
            silence_frames,
            silence_run: 0,
            min_samples,
        }
    }

    /// Alimenta amostras 16kHz mono. Retorna segmento quando endpoint detectado.
    pub fn feed(&mut self, samples: &[f32]) -> Option<Vec<f32>> {
        self.pending.extend_from_slice(samples);

        let mut processed = 0;
        while self.pending.len().saturating_sub(processed) >= FRAME_SIZE {
            let frame = &self.pending[processed..processed + FRAME_SIZE];
            processed += FRAME_SIZE;

            if self.vad.is_speech(frame) {
                self.buffer.extend_from_slice(frame);
                self.silence_run = 0;
                continue;
            }

            if self.buffer.is_empty() {
                self.silence_run = 0;
                continue;
            }

            self.silence_run += 1;
            if self.silence_run >= self.silence_frames {
                let emitted = if self.buffer.len() >= self.min_samples {
                    Some(std::mem::take(&mut self.buffer))
                } else {
                    self.buffer.clear();
                    None
                };
                self.silence_run = 0;
                self.pending.drain(..processed).for_each(drop);
                return emitted;
            }
        }

        if processed > 0 {
            self.pending.drain(..processed).for_each(drop);
        }

        None
    }

    /// Força emissão do buffer acumulado (timeout do pipeline principal).
    pub fn flush(&mut self) -> Option<Vec<f32>> {
        if !self.pending.is_empty() {
            self.buffer.extend(self.pending.drain(..));
        }

        self.silence_run = 0;

        if !self.buffer.is_empty() && self.buffer.len() >= self.min_samples {
            Some(std::mem::take(&mut self.buffer))
        } else {
            self.buffer.clear();
            None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn silence_does_not_emit() {
        let mut segmenter = Segmenter::new(3, 3840);
        assert_eq!(segmenter.feed(&[0.0; FRAME_SIZE]), None);
        assert_eq!(segmenter.flush(), None);
    }
}
