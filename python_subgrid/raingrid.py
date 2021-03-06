import os
import numpy as np
import netCDF4
import datetime
import logging
import scipy.interpolate


logger = logging.getLogger(__name__)


AREA_WIDE_RAIN = {
    '0': [0.0],
    '3': [0.30, 0.60, 0.90, 1.50, 2.10, 2.10, 1.50, 1.20, 1.05, 0.90,
          0.75, 0.60, 0.45, 0.30, 0.15],
    '4': [0.15, 0.30, 0.45, 0.60, 0.75, 0.90, 1.05, 1.20, 1.50, 2.10,
          2.10, 1.50, 0.90, 0.60, 0.30],
    '5': [0.30, 0.60, 1.50, 2.70, 2.70, 2.10, 1.50, 1.20, 1.05, 0.90,
          0.75, 0.60, 0.45, 0.30, 0.15],
    '6': [0.15, 0.30, 0.45, 0.60, 0.75, 0.90, 1.05, 1.20, 1.50, 2.10,
          2.70, 2.70, 1.50, 0.60, 0.30],
    '7': [0.6, 1.2, 2.1, 3.3, 3.3, 2.7, 2.1, 1.5, 1.2, 0.9, 0.6, 0.3],
    '8': [0.3, 0.6, 0.9, 1.2, 1.5, 2.1, 2.7, 3.3, 3.3, 2.1, 1.2, 0.6],
    '10': [1.8, 3.6, 6.3, 6.3, 5.7, 4.8, 3.6, 2.4, 1.2],
    }


class RainGrid(object):
    """
    Manage a rain grid.

    Only works on the Netherlands.
    """
    def __init__(self, subgrid, url_template='',
                 memcdf_name='precipitation.nc',
                 size_x=500, size_y=500, initial_value=0.0):
        """subgrid is used to initialize the rain grid.

        url_template is needed in function update: it fetches data from an
        opendap server
        """
        if not url_template:
            logger.warning('No url_template given.')
        self.url_template = url_template
        self.size_x = size_x
        self.size_y = size_y
        self.dt_current = None
        self.memcdf_name = memcdf_name
        self.diskless = False

        # Read pixels in model to create grid for rain
        pixels = {}
        pixels['dps'] = subgrid.get_nd('dps')[1:-1, 1:-1].T
        # ^^^ contains ghost cells? # why transposed
        pixels['dps'] = np.ma.masked_array(
            -pixels['dps'], mask=pixels['dps'] == pixels['dps'].min())
        pixels['x0p'] = subgrid.get_nd('x0p')
        pixels['dxp'] = subgrid.get_nd('dxp')
        pixels['y0p'] = subgrid.get_nd('y0p')
        pixels['dyp'] = subgrid.get_nd('dyp')
        pixels['imax'] = subgrid.get_nd('imax')
        pixels['jmax'] = subgrid.get_nd('jmax')
        pixels['x'] = np.arange(
            pixels['x0p'],
            pixels['x0p'] + pixels['imax'] * pixels['dxp'],
            pixels['dxp'])
        pixels['y'] = np.arange(
            pixels['y0p'],
            pixels['y0p'] + pixels['jmax'] * pixels['dyp'],
            pixels['dyp'])

        # Create a new grid for our rain
        self.interp = {}
        self.interp['x'] = np.linspace(pixels['x'].min(),
                                       pixels['x'].max(),
                                       num=self.size_x)
        self.interp['y'] = np.linspace(pixels['y'].min(),
                                       pixels['y'].max(),
                                       num=self.size_y)
        self.interp['X'], self.interp['Y'] = np.meshgrid(self.interp['x'],
                                                         self.interp['y'])

        # TODO: replace precipitation.nc with a unique name
        # TODO: add diskless=True, requires netcdf version >= 4.2.x
        # For now use netcdf classic, issue with netcdf redefinition in hdf5
        # format
        memcdf = netCDF4.Dataset(self.memcdf_name,
                                 mode="w",
                                 diskless=self.diskless,
                                 format='NETCDF3_64BIT')

        memcdf.createDimension("nx", self.interp['x'].shape[0])
        logger.info('interp x shape %r' % self.interp['x'].shape[0])
        memcdf.createDimension("ny", self.interp['y'].shape[0])
        logger.info('interp y shape %r' % self.interp['y'].shape[0])

        # Put coordinates and values in the netcdf
        var = memcdf.createVariable(
            "x", datatype="double", dimensions=("nx",))
        var[:] = self.interp['x']
        var.standard_name = 'projected_x_coordinate'
        var.units = 'm'

        var = memcdf.createVariable(
            "y", datatype="double", dimensions=("ny", ))
        var[:] = self.interp['y']
        var.standard_name = 'projected_y_coordinate'
        var.units = 'm'

        rainfall_var = memcdf.createVariable(
            "rainfall", datatype="double", dimensions=("ny", "nx"),
            fill_value=-9999)

        rainfall_var.standard_name = 'precipitation'
        rainfall_var.coordinates = 'y x'
        rainfall_var.units = 'm/min'
        memcdf.close()

        self.fill(initial_value)

    def fill(self, value=0.0):
        """Fill rainfall variable"""
        memcdf = netCDF4.Dataset(
            self.memcdf_name, mode="r+", diskless=self.diskless)
        rainfall_var = memcdf.variables["rainfall"]
        rainfall_var[:, :] = value
        # interp['Z']*(1/5.0)*(1/1000.0) #  mm/5min * 5min/min * m/mm -> m/min
        memcdf.sync()
        memcdf.close()

    def update(self, dt, multiplier=1.0):
        """Update the (interpolated) grid with given datetime

        Return True if grid has changed"""
        if not self.url_template:
            logger.error('No url_template given, cannot use opendap server.')
            return

        # Quantize on 5 minutes
        minutes = dt.minute / 5 * 5
        dt_request = datetime.datetime(dt.year, dt.month, dt.day, dt.hour,
                                       minutes, 0)
        if dt_request == self.dt_current:
            # Nothing to do
            return False

        url = self.url_template.format(year=dt.year, month='%02d' % dt.month)
        logger.info('Reading rain data from %s...' % url)
        # url = 'http://opendap.nationaleregenradar.nl/thredds/dodsC/radar/TF0005_A/2013/10/01/RAD_TF0005_A_20131001000000.h5'
        ds = netCDF4.Dataset(url)

        rain = {}
        rain['time'] = netCDF4.num2date(ds.variables['time'][:],
                                        ds.variables['time'].units)
        rain['x'] = ds.variables['east'][:]
        rain['y'] = ds.variables['north'][:]
        rain['P'] = ds.variables['precipitation']

        # Pick the index of the requested datetime.
        time_idx = np.where(rain['time'] == dt_request)[0]
        rain['p'] = rain['P'][:, :, time_idx]
        # ^^^ x, y expected by some routines

        # Interpolate rain data rain -> interp
        logger.info('Interpolating rain data...')
        F = scipy.interpolate.RectBivariateSpline(
            rain['x'].ravel(),
            rain['y'][::-1],
            # reverse y axis and swap x,y
            np.swapaxes(rain['p'][::-1, :].filled(0), 0, 1)
        )

        # Evaluate the interpolation function on the new grid
        self.interp['z'] = F.ev(self.interp['X'].ravel(),
                                self.interp['Y'].ravel())

        self.interp['Z'] = self.interp['z'].reshape(self.interp['X'].shape)

        logger.info('Updating memcdf...')

        ds.close()

        memcdf = netCDF4.Dataset(self.memcdf_name,
                                 mode="a",
                                 diskless=self.diskless)
        rainfall_var = memcdf.variables["rainfall"]
        rainfall_var[:, :] = (self.interp['Z'] * (1 / 5.0) * (1 / 1000.0) *
                              multiplier)
        # ^^^ mm/5min * 5min/min * m/mm -> m/min
        memcdf.sync()
        memcdf.close()

        logger.info('Rainfall sum (testing): %f',
                    np.sum(self.interp['Z'] * (1 / 5.0) * (1 / 1000.0) *
                           multiplier))

        self.dt_current = dt_request
        return True


class AreaWideRainGrid(RainGrid):
    def __init__(self, subgrid, url_template='dummy',
                 memcdf_name='area_wide.nc', *args, **kwargs):

        self.current_value = None
        self.current_rain_definition = None
        self.memcdf_name = memcdf_name
        super(AreaWideRainGrid, self).__init__(
            subgrid,
            url_template=url_template,
            memcdf_name=self.memcdf_name, *args, **kwargs)

    # It has the handy fill method, init with subgrid only
    def update(self, rain_definition, time_seconds):
        idx = int(time_seconds) // 300
        if idx < len(AREA_WIDE_RAIN[rain_definition]) and idx >= 0:
            new_value = AREA_WIDE_RAIN[rain_definition][idx]
            self.cumulative = sum(AREA_WIDE_RAIN[rain_definition][:idx])
        else:
            new_value = 0.0
            if idx > 0:
                self.cumulative = sum(AREA_WIDE_RAIN[rain_definition])
            else:
                self.cumulative = 0

        if ((new_value != self.current_value) or
            (rain_definition != self.current_rain_definition)):
            logger.debug('New intensity area wide rain: time %ds new value %f',
                         time_seconds, new_value)
            # convert mm/300s to mm/min????
            self.fill(new_value / 300 * 60)
            self.current_value = new_value
            self.current_rain_definition = rain_definition
            return True
        return False


class RainGridContainer(RainGrid):
    """Container for rain grids"""
    def __init__(self, subgrid, url_template='dummy', *args, **kwargs):
        self.grid_names = set([])
        self.memcdf_name = 'container_grid.nc'
        super(RainGridContainer, self).__init__(
            subgrid, url_template,
            memcdf_name=self.memcdf_name, *args, **kwargs)

    def register(self, name):
        self.grid_names.add(name)

    def unregister(self, name):
        self.grid_names.remove(name)

    def update(self):
        """Recalculate sum of grids"""
        memcdf = netCDF4.Dataset(self.memcdf_name, mode="a", diskless=False)
        rainfall_var = memcdf.variables["rainfall"]

        if not self.grid_names:
            rainfall_var[:, :] = 0
        first = True
        for grid_name in self.grid_names:
            _memcdf = netCDF4.Dataset(grid_name, mode="r+", diskless=False)
            if first:
                rainfall_var[:, :] = _memcdf.variables["rainfall"][:, :]
                first = False
            else:
                rainfall_var[:, :] += _memcdf.variables["rainfall"][:, :]
            _memcdf.close()
        memcdf.sync()
        memcdf.close()

    def delete_memcdf(self):
        if os.path.exists(self.memcdf_name):
            os.remove(self.memcdf_name)
