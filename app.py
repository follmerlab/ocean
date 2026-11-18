from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import seabreeze.spectrometers as sb
import numpy as np
import threading
import time
import os

app = Flask(__name__)
CORS(app)

# Global variables
spectrometer = None
dark_spectrum = None
reference_spectrum = None
is_acquiring = False
acquisition_thread = None
current_spectrum_data = None
integration_time = 1.0  # seconds

def initialize_spectrometer():
    """Initialize the spectrometer connection"""
    global spectrometer
    try:
        # Close existing connection if any
        if spectrometer is not None:
            try:
                spectrometer.close()
            except:
                pass
        
        devices = sb.list_devices()
        if not devices:
            return None, "No spectrometers found. Check USB connection and permissions."
        
        print(f"Found {len(devices)} device(s): {devices}")
        spectrometer = sb.Spectrometer(devices[0])
        spectrometer.integration_time_micros(int(integration_time * 1_000_000))
        return spectrometer, None
    except Exception as e:
        print(f"Error initializing spectrometer: {e}")
        return None, str(e)

def continuous_acquisition():
    """Continuously acquire spectra in a separate thread"""
    global is_acquiring, current_spectrum_data, spectrometer
    
    while is_acquiring:
        try:
            if spectrometer is None:
                time.sleep(0.1)
                continue
                
            wavelengths = spectrometer.wavelengths()
            intensities = spectrometer.intensities()
            
            # Apply dark subtraction if available
            if dark_spectrum is not None:
                intensities = intensities - dark_spectrum
            
            # Calculate absorbance if reference is available
            absorbance = None
            transmittance = None
            if reference_spectrum is not None:
                # Avoid division by zero
                ref_corrected = reference_spectrum.copy()
                if dark_spectrum is not None:
                    ref_corrected = ref_corrected - dark_spectrum
                ref_corrected[ref_corrected <= 0] = 1e-10
                intensities_safe = intensities.copy()
                intensities_safe[intensities_safe <= 0] = 1e-10
                
                transmittance = intensities_safe / ref_corrected
                absorbance = -np.log10(transmittance)
            
            current_spectrum_data = {
                'wavelengths': wavelengths.tolist(),
                'intensities': intensities.tolist(),
                'absorbance': absorbance.tolist() if absorbance is not None else None,
                'transmittance': transmittance.tolist() if transmittance is not None else None,
                'timestamp': time.time()
            }
            
            time.sleep(0.1)  # Small delay to prevent overwhelming the system
            
        except Exception as e:
            print(f"Error in continuous acquisition: {e}")
            time.sleep(0.5)

@app.route('/')
def index():
    """Serve the main page"""
    return render_template('index.html')

@app.route('/api/initialize', methods=['POST'])
def api_initialize():
    """Initialize or reinitialize the spectrometer"""
    global spectrometer
    spec, error = initialize_spectrometer()
    if error:
        return jsonify({'success': False, 'error': error})
    return jsonify({'success': True, 'message': 'Spectrometer initialized'})

@app.route('/api/status', methods=['GET'])
def api_status():
    """Get the current status of the spectrometer"""
    return jsonify({
        'connected': spectrometer is not None,
        'acquiring': is_acquiring,
        'has_dark': dark_spectrum is not None,
        'has_reference': reference_spectrum is not None,
        'integration_time': integration_time
    })

@app.route('/api/set_integration_time', methods=['POST'])
def api_set_integration_time():
    """Set the integration time (in seconds)"""
    global integration_time, spectrometer
    
    data = request.json
    time_sec = float(data.get('time', 1.0))
    
    # Clamp between 0.001 (1ms) and 10 seconds
    time_sec = max(0.001, min(10.0, time_sec))
    integration_time = time_sec
    
    if spectrometer is not None:
        try:
            spectrometer.integration_time_micros(int(time_sec * 1_000_000))
            return jsonify({'success': True, 'integration_time': integration_time})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    return jsonify({'success': True, 'integration_time': integration_time})

@app.route('/api/capture_dark', methods=['POST'])
def api_capture_dark():
    """Capture a dark spectrum"""
    global dark_spectrum, spectrometer
    
    if spectrometer is None:
        return jsonify({'success': False, 'error': 'Spectrometer not initialized'})
    
    try:
        wavelengths = spectrometer.wavelengths()
        dark_spectrum = spectrometer.intensities()
        return jsonify({
            'success': True, 
            'message': 'Dark spectrum captured',
            'wavelengths': wavelengths.tolist(),
            'spectrum': dark_spectrum.tolist()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/capture_reference', methods=['POST'])
def api_capture_reference():
    """Capture a reference spectrum"""
    global reference_spectrum, spectrometer, dark_spectrum
    
    if spectrometer is None:
        return jsonify({'success': False, 'error': 'Spectrometer not initialized'})
    
    try:
        wavelengths = spectrometer.wavelengths()
        reference_spectrum = spectrometer.intensities()
        
        # Also return dark-corrected version for display
        display_spectrum = reference_spectrum.copy()
        if dark_spectrum is not None:
            display_spectrum = display_spectrum - dark_spectrum
        
        return jsonify({
            'success': True, 
            'message': 'Reference spectrum captured',
            'wavelengths': wavelengths.tolist(),
            'spectrum': reference_spectrum.tolist(),
            'display_spectrum': display_spectrum.tolist()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/clear_dark', methods=['POST'])
def api_clear_dark():
    """Clear the dark spectrum"""
    global dark_spectrum
    dark_spectrum = None
    return jsonify({'success': True, 'message': 'Dark spectrum cleared'})

@app.route('/api/clear_reference', methods=['POST'])
def api_clear_reference():
    """Clear the reference spectrum"""
    global reference_spectrum
    reference_spectrum = None
    return jsonify({'success': True, 'message': 'Reference spectrum cleared'})

@app.route('/api/start_live', methods=['POST'])
def api_start_live():
    """Start continuous acquisition"""
    global is_acquiring, acquisition_thread, spectrometer
    
    if spectrometer is None:
        return jsonify({'success': False, 'error': 'Spectrometer not initialized'})
    
    if not is_acquiring:
        is_acquiring = True
        acquisition_thread = threading.Thread(target=continuous_acquisition, daemon=True)
        acquisition_thread.start()
        return jsonify({'success': True, 'message': 'Live acquisition started'})
    
    return jsonify({'success': True, 'message': 'Already acquiring'})

@app.route('/api/stop_live', methods=['POST'])
def api_stop_live():
    """Stop continuous acquisition"""
    global is_acquiring
    is_acquiring = False
    return jsonify({'success': True, 'message': 'Live acquisition stopped'})

@app.route('/api/get_spectrum', methods=['GET'])
def api_get_spectrum():
    """Get the current spectrum data"""
    if current_spectrum_data is None:
        return jsonify({'success': False, 'error': 'No data available'})
    
    return jsonify({
        'success': True,
        'data': current_spectrum_data
    })

@app.route('/api/capture_single', methods=['POST'])
def api_capture_single():
    """Capture a single spectrum"""
    global spectrometer, dark_spectrum, reference_spectrum
    
    if spectrometer is None:
        return jsonify({'success': False, 'error': 'Spectrometer not initialized'})
    
    try:
        wavelengths = spectrometer.wavelengths()
        intensities = spectrometer.intensities()
        
        print(f"Captured spectrum: {len(wavelengths)} points, wavelength range: {wavelengths[0]:.1f}-{wavelengths[-1]:.1f} nm")
        
        # Apply dark subtraction if available
        if dark_spectrum is not None:
            intensities = intensities - dark_spectrum
            print("Dark spectrum subtracted")
        
        # Calculate absorbance if reference is available
        absorbance = None
        transmittance = None
        if reference_spectrum is not None:
            ref_corrected = reference_spectrum.copy()
            if dark_spectrum is not None:
                ref_corrected = ref_corrected - dark_spectrum
            ref_corrected[ref_corrected <= 0] = 1e-10
            intensities_safe = intensities.copy()
            intensities_safe[intensities_safe <= 0] = 1e-10
            
            transmittance = intensities_safe / ref_corrected
            absorbance = -np.log10(transmittance)
            print("Absorbance/transmittance calculated")
        
        result = {
            'success': True,
            'data': {
                'wavelengths': wavelengths.tolist(),
                'intensities': intensities.tolist(),
                'absorbance': absorbance.tolist() if absorbance is not None else None,
                'transmittance': transmittance.tolist() if transmittance is not None else None,
                'timestamp': time.time()
            }
        }
        print(f"Returning data with {len(result['data']['wavelengths'])} wavelength points")
        return jsonify(result)
    except Exception as e:
        print(f"Error in capture_single: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    import sys
    # Only initialize on the main process, not the reloader
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        print("Starting server (initializing on first request)...")
    else:
        print("Initializing spectrometer...")
        spec, error = initialize_spectrometer()
        if error:
            print(f"Warning: {error}")
            print("You can try to initialize from the web interface.")
        else:
            print("Spectrometer initialized successfully!")
    
    print("\nWeb server starting...")
    print("Open your browser and navigate to: http://localhost:5001")
    app.run(debug=True, host='0.0.0.0', port=5001, threaded=True, use_reloader=True)
