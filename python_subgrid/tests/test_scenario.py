"""
Test the library on desired behavior by running it on several models.
"""
import os
import unittest

from python_subgrid.tests.utils import colorlogs
from python_subgrid.tools.scenario import EventContainer
from python_subgrid.tools.scenario import RadarGrid

colorlogs()
# We don't want to know about ctypes here
# only in the test_wrapper and the wrapper itself.


class TestCase(unittest.TestCase):

    def setUp(self):
        self.scenario_path = 'python_subgrid/tests/scenario'
        self.radar_grid_path = os.path.join(
            self.scenario_path, EventContainer.radar_grids_filename)
        self.area_wide_rain_grid_path = os.path.join(
            self.scenario_path, EventContainer.area_wide_rain_grids_filename)
        self.radar_url_template = (
            'http://opendap.nationaleregenradar.nl/'
            'thredds/dodsC/radar/TF0005_A/{year}/{month}/01/'
            'RAD_TF0005_A_{year}{month}01000000.h5')

    def tearDown(self):
        pass

    def test_smoke(self):
        EventContainer()

    def test_events(self):
        event_container = EventContainer(self.scenario_path)
        self.assertEquals(len(
            event_container.events(event_object=RadarGrid)), 3)

    def test_radar_grid_time(self):
        event_container = EventContainer(self.scenario_path)
        self.assertEquals(
            len(event_container.events(
                event_object=RadarGrid, sim_time=120.)), 1)

    def test_radar_grid_start_within(self):
        event_container = EventContainer(self.scenario_path)
        self.assertEquals(len(event_container.events(
            event_object=RadarGrid, sim_time=120, start_within=30)), 1)
        self.assertEquals(len(event_container.events(
            event_object=RadarGrid, sim_time=150, start_within=20)), 0)

    def test_radar_grid_ends_within(self):
        event_container = EventContainer(self.scenario_path)
        # no ending
        self.assertEquals(len(event_container.events(
            event_object=RadarGrid, sim_time=10000, ends_within=20)), 0)
        # end at 1000
        self.assertEquals(len(event_container.events(
            event_object=RadarGrid, sim_time=1000, ends_within=20)), 1)

    # to test_functional?
    # def test_radar_grid_init(self):
    #     event_container = EventContainer(self.scenario_path)
    #     events = event_container.events(
    #         event_object=RadarGrid, sim_time=130, start_within=30)
    #     with SubgridWrapper(mdu=self.default_mdu) as subgrid:
    #         for e in events:
    #             e.init(subgrid, self.radar_url_template)

        # # From player.py
        # logger.info('Preparing radar rain grid...')
        # size_x, size_y = 500, 500
        # self.rain_grid = RainGrid(
        #     self, self.radar_url_template,
        #     initial_value=0.,
        #     size_x=size_x, size_y=size_y)

        # self.subscribe_dataset(self.container_rain_grid.memcdf_name)
