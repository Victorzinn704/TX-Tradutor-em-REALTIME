use crate::CaptureError;

#[derive(Debug, Clone)]
pub struct DeviceInfo {
    pub index:              u32,
    pub name:               String,
    pub is_loopback:        bool,
    pub default_sample_rate: u32,
    pub max_channels:       u16,
}

#[cfg(windows)]
struct DeviceEntry {
    id: String,
    info: DeviceInfo,
}

#[cfg(windows)]
fn info_from_device(
    device: &wasapi::Device,
    index: u32,
    is_loopback: bool,
) -> Result<DeviceEntry, CaptureError> {
    let name = device
        .get_friendlyname()
        .map_err(|error| CaptureError::Wasapi(error.to_string()))?;
    let audio_client = device
        .get_iaudioclient()
        .map_err(|error| CaptureError::Wasapi(error.to_string()))?;
    let format = audio_client
        .get_mixformat()
        .map_err(|error| CaptureError::Wasapi(error.to_string()))?;
    let default_sample_rate = format.get_samplespersec();
    let max_channels = format.get_nchannels();
    let id = device
        .get_id()
        .map_err(|error| CaptureError::Wasapi(error.to_string()))?;

    if default_sample_rate == 0 || max_channels == 0 {
        return Err(CaptureError::FormatUnsupported(name));
    }

    Ok(DeviceEntry {
        id,
        info: DeviceInfo {
            index,
            name,
            is_loopback,
            default_sample_rate,
            max_channels,
        },
    })
}

#[cfg(windows)]
fn collect_direction(direction: wasapi::Direction, is_loopback: bool) -> Result<Vec<DeviceEntry>, CaptureError> {
    let collection = wasapi::DeviceCollection::new(&direction)
        .map_err(|error| CaptureError::Wasapi(error.to_string()))?;
    let device_count = collection
        .get_nbr_devices()
        .map_err(|error| CaptureError::Wasapi(error.to_string()))?;

    let mut devices = Vec::new();

    for index in 0..device_count {
        match collection.get_device_at_index(index) {
            Ok(device) => match info_from_device(&device, index, is_loopback) {
                Ok(entry) => devices.push(entry),
                Err(error) => tracing::warn!(?error, index, "ignoring WASAPI device"),
            },
            Err(error) => tracing::warn!(?error, index, "ignoring WASAPI device"),
        }
    }

    Ok(devices)
}

#[cfg(windows)]
fn collect_devices() -> Result<Vec<DeviceEntry>, CaptureError> {
    let mut devices = collect_direction(wasapi::Direction::Capture, false)?;
    devices.extend(collect_direction(wasapi::Direction::Render, true)?);
    Ok(devices)
}

pub fn enumerate_devices() -> Result<Vec<DeviceInfo>, CaptureError> {
    #[cfg(windows)]
    {
        collect_devices().map(|devices| devices.into_iter().map(|entry| entry.info).collect())
    }

    #[cfg(not(windows))]
    {
        Err(CaptureError::Wasapi(
            "WASAPI device enumeration is only available on Windows".to_string(),
        ))
    }
}

pub fn find_default_mic() -> Result<DeviceInfo, CaptureError> {
    #[cfg(windows)]
    {
        let default_device = wasapi::get_default_device(&wasapi::Direction::Capture)
            .map_err(|error| CaptureError::Wasapi(error.to_string()))?;
        let default_id = default_device
            .get_id()
            .map_err(|error| CaptureError::Wasapi(error.to_string()))?;

        collect_direction(wasapi::Direction::Capture, false)?
            .into_iter()
            .find(|entry| entry.id == default_id)
            .map(|entry| entry.info)
            .ok_or_else(|| CaptureError::DeviceNotFound(default_id))
    }

    #[cfg(not(windows))]
    {
        Err(CaptureError::Wasapi(
            "WASAPI device enumeration is only available on Windows".to_string(),
        ))
    }
}

pub fn find_loopback() -> Result<DeviceInfo, CaptureError> {
    #[cfg(windows)]
    {
        collect_direction(wasapi::Direction::Render, true)?
            .into_iter()
            .next()
            .map(|entry| entry.info)
            .ok_or_else(|| CaptureError::DeviceNotFound("loopback".to_string()))
    }

    #[cfg(not(windows))]
    {
        Err(CaptureError::Wasapi(
            "WASAPI device enumeration is only available on Windows".to_string(),
        ))
    }
}

pub fn find_by_name(pattern: &str) -> Result<Vec<DeviceInfo>, CaptureError> {
    let pattern = pattern.to_lowercase();
    enumerate_devices().map(|devices| {
        devices
            .into_iter()
            .filter(|device| device.name.to_lowercase().contains(&pattern))
            .collect()
    })
}
