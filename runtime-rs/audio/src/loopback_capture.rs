use crate::{AudioCapture, AudioCallback, CaptureError};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    mpsc,
    Arc,
};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

#[cfg(windows)]
use wasapi::{Direction, SampleType, WaveFormat};
#[cfg(windows)]
use wasapi::ShareMode;

pub struct LoopbackCapture {
    source_id: String,
    device_index: u32,
    sample_rate: u32,
    channels: u16,
    running: Arc<AtomicBool>,
    worker: Option<JoinHandle<()>>,
}

impl LoopbackCapture {
    pub fn from_device_info(device: &crate::device_enum::DeviceInfo) -> Self {
        Self::new(device.index, device.default_sample_rate, device.max_channels)
    }

    pub fn new(device_index: u32, sample_rate: u32, channels: u16) -> Self {
        Self {
            source_id: format!("loopback:{device_index}"),
            device_index,
            sample_rate,
            channels,
            running: Arc::new(AtomicBool::new(false)),
            worker: None,
        }
    }

    pub fn default_device() -> Result<Self, CaptureError> {
        crate::device_enum::find_loopback().map(|device| Self::from_device_info(&device))
    }
}

fn bytes_to_f32_samples(bytes: &[u8]) -> Vec<f32> {
    bytes
        .chunks_exact(4)
        .map(|chunk| f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]))
        .collect()
}

#[cfg(windows)]
fn resolve_device_index(device_index: u32) -> Result<wasapi::Device, CaptureError> {
    let collection = wasapi::DeviceCollection::new(&Direction::Render)
        .map_err(|error| CaptureError::Wasapi(error.to_string()))?;

    collection
        .get_device_at_index(device_index)
        .map_err(|error| CaptureError::Wasapi(error.to_string()))
}

fn resolve_device_info(device_index: u32) -> Result<crate::device_enum::DeviceInfo, CaptureError> {
    crate::device_enum::enumerate_devices()?
        .into_iter()
        .find(|device| device.is_loopback && device.index == device_index)
        .ok_or_else(|| CaptureError::DeviceNotFound(format!("loopback:{device_index}")))
}

#[cfg(windows)]
fn capture_worker(
    device_index: u32,
    sample_rate: u32,
    channels: u16,
    running: Arc<AtomicBool>,
    ready: mpsc::SyncSender<Result<(), CaptureError>>,
    callback: AudioCallback,
) {
    let _ = wasapi::initialize_mta();

    // --- init phase: send readiness before entering the capture loop ---
    let init_result: Result<_, CaptureError> = (|| {
        let device = resolve_device_index(device_index)?;
        let mut audio_client = device
            .get_iaudioclient()
            .map_err(|error| CaptureError::StreamOpen(error.to_string()))?;

        let (_, min_period) = audio_client
            .get_periods()
            .map_err(|error| CaptureError::Wasapi(error.to_string()))?;

        let desired_format = WaveFormat::new(
            32,
            32,
            &SampleType::Float,
            sample_rate as usize,
            channels as usize,
            None,
        );

        audio_client
            .initialize_client(
                &desired_format,
                min_period as i64,
                &Direction::Render,
                &ShareMode::Shared,
                true,
            )
            .map_err(|error| CaptureError::FormatUnsupported(error.to_string()))?;

        let h_event = audio_client
            .set_get_eventhandle()
            .map_err(|error| CaptureError::StreamOpen(error.to_string()))?;

        let capture_client = audio_client
            .get_audiocaptureclient()
            .map_err(|error| CaptureError::StreamOpen(error.to_string()))?;

        audio_client
            .start_stream()
            .map_err(|error| CaptureError::StreamOpen(error.to_string()))?;

        let block_align = desired_format.get_blockalign() as usize;
        Ok((capture_client, audio_client, h_event, block_align))
    })();

    let (capture_client, audio_client, h_event, block_align) = match init_result {
        Err(e) => {
            let _ = ready.send(Err(e));
            return;
        }
        Ok(v) => {
            let _ = ready.send(Ok(()));
            v
        }
    };

    // --- capture loop: runs after start() has already returned Ok ---
    while running.load(Ordering::SeqCst) {
        if h_event.wait_for_event(100).is_err() {
            break;
        }

        let frames = match capture_client
            .get_next_nbr_frames()
            .map_err(|error| CaptureError::Wasapi(error.to_string()))
        {
            Err(_) => break,
            Ok(None) => continue,
            Ok(Some(0)) => continue,
            Ok(Some(n)) => n,
        };

        let mut raw = vec![0_u8; frames as usize * block_align];
        let (frames_read, buffer_flags) = match capture_client
            .read_from_device(block_align, &mut raw)
            .map_err(|error| CaptureError::Wasapi(error.to_string()))
        {
            Err(_) => break,
            Ok(v) => v,
        };

        if buffer_flags.silent {
            let silence = vec![0.0_f32; frames_read as usize * channels as usize];
            callback(&silence, sample_rate, channels);
            continue;
        }

        let byte_len = frames_read as usize * block_align;
        let samples = bytes_to_f32_samples(&raw[..byte_len]);
        if !samples.is_empty() {
            callback(&samples, sample_rate, channels);
        }
    }

    let _ = audio_client.stop_stream();
}

impl AudioCapture for LoopbackCapture {
    fn source_id(&self) -> &str {
        &self.source_id
    }
    fn sample_rate(&self) -> u32 {
        self.sample_rate
    }
    fn channels(&self) -> u16 {
        self.channels
    }
    fn start(&mut self, callback: AudioCallback) -> Result<(), CaptureError> {
        if self.worker.is_some() {
            return Err(CaptureError::StreamOpen(
                "loopback capture already running".to_string(),
            ));
        }

        let device = resolve_device_info(self.device_index)?;

        self.sample_rate = device.default_sample_rate;
        self.channels = device.max_channels;

        let running = Arc::clone(&self.running);
        running.store(true, Ordering::SeqCst);
        let (ready_tx, ready_rx) = mpsc::sync_channel(1);
        let device_index = self.device_index;
        let sample_rate = self.sample_rate;
        let channels = self.channels;
        let worker = thread::spawn(move || {
            capture_worker(device_index, sample_rate, channels, running, ready_tx, callback)
        });
        self.worker = Some(worker);

        match ready_rx.recv() {
            Ok(Ok(())) => Ok(()),
            Ok(Err(error)) => {
                self.stop();
                Err(error)
            }
            Err(error) => {
                self.stop();
                Err(CaptureError::StreamOpen(format!(
                    "failed to initialize loopback capture: {error}"
                )))
            }
        }
    }
    fn stop(&mut self) {
        self.running.store(false, Ordering::SeqCst);
        if let Some(worker) = self.worker.take() {
            let deadline = Instant::now() + Duration::from_millis(500);
            while !worker.is_finished() && Instant::now() < deadline {
                thread::sleep(Duration::from_millis(10));
            }

            if worker.is_finished() {
                let _ = worker.join();
            }
        }
    }
}

#[cfg(not(windows))]
impl AudioCapture for LoopbackCapture {
    fn source_id(&self) -> &str {
        &self.source_id
    }

    fn sample_rate(&self) -> u32 {
        self.sample_rate
    }

    fn channels(&self) -> u16 {
        self.channels
    }

    fn start(&mut self, _callback: AudioCallback) -> Result<(), CaptureError> {
        Err(CaptureError::Wasapi(
            "loopback capture is only available on Windows".to_string(),
        ))
    }

    fn stop(&mut self) {}
}
