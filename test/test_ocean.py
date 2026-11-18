import seabreeze.spectrometers as sb

devs = sb.list_devices()
if not devs:
    raise RuntimeError("No spectrometers found (SeaBreeze).")

spec = sb.Spectrometer(devs[0])
spec.integration_time_micros(100000)

wl = spec.wavelengths()
intens = spec.intensities()

print(wl[:5], intens[:5])
spec.close()

