# Ocean Optics Flame Spectrometer - Browser Interface

A modern, browser-based interface for controlling and acquiring spectra from the Ocean Optics Flame microspectrometer.

## Features

- 🔬 **Real-time Spectral Acquisition**: Live monitoring mode with continuous spectrum updates
- 📊 **Multiple Display Modes**: View data as Intensity, Absorbance, or Transmittance
- ⚫ **Dark Spectrum Correction**: Capture and subtract dark (zero) spectra
- 📈 **Reference Spectrum**: Capture reference for absorbance/transmittance calculations
- ⏱️ **Adjustable Integration Time**: Set acquisition time between 0.5 and 10 seconds
- 🎯 **Single Shot Mode**: Capture individual spectra on demand
- 💻 **Modern UI**: Clean, responsive interface with real-time status indicators

## Installation

1. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Install SeaBreeze backend** (if not already installed):
   
   For macOS:
   ```bash
   brew install libusb
   ```
   
   For Linux:
   ```bash
   sudo apt-get install libusb-1.0-0-dev
   ```
   
   For Windows:
   - Download and install the Ocean Optics OmniDriver or follow SeaBreeze documentation

## Usage

1. **Connect your Ocean Optics Flame spectrometer** to your computer via USB

2. **Start the web server**:
   ```bash
   python app.py
   ```

3. **Open your browser** and navigate to:
   ```
   http://localhost:5000
   ```

## Quick Start Guide

### Initial Setup

1. **Initialize Spectrometer**: Click "Initialize Spectrometer" to connect to your device
2. **Set Integration Time**: Adjust the slider to set your desired integration time (0.5-10 seconds)

### Calibration Workflow

1. **Capture Dark Spectrum**:
   - Block all light from entering the spectrometer
   - Click "Capture Dark Spectrum"
   - This will be automatically subtracted from all subsequent measurements

2. **Capture Reference Spectrum** (optional, for absorbance/transmittance):
   - Place your reference sample (e.g., blank cuvette, solvent)
   - Click "Capture Reference Spectrum"
   - This enables absorbance and transmittance display modes

### Acquisition Modes

#### Live Monitoring
- Click "Start Live Monitoring" to begin continuous acquisition
- The spectrum will update in real-time (~2 Hz)
- Perfect for monitoring reactions or adjusting sample positioning
- Click "Stop Live Monitoring" to pause

#### Single Spectrum
- Click "Capture Single Spectrum" to take one measurement
- Ideal for recording individual samples

### Display Modes

Switch between different data representations:
- **Intensity**: Raw intensity values (with dark subtraction if enabled)
- **Absorbance**: -log₁₀(T) where T = I/I₀ (requires reference spectrum)
- **Transmittance**: I/I₀ ratio (requires reference spectrum)

## API Endpoints

The Flask backend provides a RESTful API:

- `POST /api/initialize` - Initialize spectrometer connection
- `GET /api/status` - Get current system status
- `POST /api/set_integration_time` - Set integration time (0.5-10s)
- `POST /api/capture_dark` - Capture dark spectrum
- `POST /api/capture_reference` - Capture reference spectrum
- `POST /api/clear_dark` - Clear stored dark spectrum
- `POST /api/clear_reference` - Clear stored reference spectrum
- `POST /api/start_live` - Start continuous acquisition
- `POST /api/stop_live` - Stop continuous acquisition
- `GET /api/get_spectrum` - Get current spectrum data
- `POST /api/capture_single` - Capture a single spectrum

## File Structure

```
ocean/
├── app.py                  # Flask backend server
├── templates/
│   └── index.html         # Frontend web interface
├── test/
│   ├── test_ocean.py      # Basic spectrometer test
│   └── test_ocean_aq.py   # Acquisition test with plotting
├── requirements.txt        # Python dependencies
└── README.md              # This file
```

## Troubleshooting

### Spectrometer Not Found
- Ensure the device is properly connected via USB
- Check that you have the correct drivers/permissions
- On Linux, you may need to add udev rules for USB access
- Try unplugging and reconnecting the device

### Permission Errors (Linux/macOS)
```bash
# Add your user to the appropriate group
sudo usermod -a -G plugdev $USER
# or
sudo usermod -a -G dialout $USER
```

### Port Already in Use
If port 5000 is already in use, modify `app.py`:
```python
app.run(debug=True, host='0.0.0.0', port=5001, threaded=True)
```

## Technical Details

- **Backend**: Flask (Python)
- **Frontend**: Vanilla JavaScript with Plotly.js for visualization
- **Spectrometer Interface**: SeaBreeze library
- **Data Format**: JSON for client-server communication
- **Threading**: Background thread for continuous acquisition

## Advanced Usage

### Programmatic Access

You can also access the spectrometer programmatically:

```python
import requests

# Capture a single spectrum
response = requests.post('http://localhost:5000/api/capture_single')
data = response.json()

wavelengths = data['data']['wavelengths']
intensities = data['data']['intensities']
```

### Custom Integration Time via API

```python
import requests

requests.post('http://localhost:5000/api/set_integration_time', 
              json={'time': 2.5})  # 2.5 seconds
```

## Safety Notes

- Always ensure proper dark spectrum calibration for accurate measurements
- Reference spectra should be captured with the same integration time as your samples
- The integration time slider is clamped between 0.5-10 seconds for safety
- Dark and reference spectra persist until explicitly cleared or server restart

## License

This software is provided for research and educational purposes.

## Support

For issues related to:
- **SeaBreeze library**: https://github.com/ap--/python-seabreeze
- **Ocean Optics devices**: https://www.oceaninsight.com/

## Version

Current version: 1.0.0
