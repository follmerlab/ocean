import seabreeze.spectrometers as sb

spec = sb.Spectrometer(sb.list_devices()[0])
spec.integration_time_micros(100000)

wl = spec.wavelengths()
intens = spec.intensities()

print("Wavelengths:", wl[:5])
print("Intensities:", intens[:5])

spec.close()

import matplotlib.pyplot as plt

plt.plot(wl, intens)
plt.xlabel("Wavelength (nm)")
plt.ylabel("Intensity (a.u.)")
plt.show()

