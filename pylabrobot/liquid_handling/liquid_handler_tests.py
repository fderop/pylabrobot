""" Tests for LiquidHandler """
# pylint: disable=missing-class-docstring

from typing import Any, Dict, List, Optional, cast
import unittest
import unittest.mock

from pylabrobot.liquid_handling.errors import (
  ChannelHasTipError,
  ChannelHasNoTipError,
  TipSpotHasTipError,
  TipSpotHasNoTipError,
)
from pylabrobot.liquid_handling import no_tip_tracking, set_tip_tracking

from . import backends
from .liquid_handler import LiquidHandler
from .resources import (
  Coordinate,
  TIP_CAR_480_A00,
  PLT_CAR_L5AC_A00,
  Cos_96_DW_1mL,
  Cos_96_DW_500ul,
  TipRack,
)
from .resources.hamilton import STARLetDeck
from .resources.ml_star import STF_L, HTF_L
from .standard import Pickup, Drop, Aspiration, Dispense


class TestLiquidHandlerLayout(unittest.TestCase):
  def setUp(self):
    self.backend = backends.SaverBackend(num_channels=8)
    self.deck = STARLetDeck()
    self.lh = LiquidHandler(self.backend, deck=self.deck)

  def test_resource_assignment(self):
    tip_car = TIP_CAR_480_A00(name="tip_carrier")
    tip_car[0] = STF_L(name="tip_rack_01")
    tip_car[1] = STF_L(name="tip_rack_02")
    tip_car[3] = HTF_L("tip_rack_04")

    plt_car = PLT_CAR_L5AC_A00(name="plate carrier")
    plt_car[0] = Cos_96_DW_1mL(name="aspiration plate")
    plt_car[2] = Cos_96_DW_500ul(name="dispense plate")

    self.deck.assign_child_resource(tip_car, rails=1)
    self.deck.assign_child_resource(plt_car, rails=21)

    # Test placing a carrier at a location where another carrier is located.
    with self.assertRaises(ValueError):
      dbl_plt_car_1 = PLT_CAR_L5AC_A00(name="double placed carrier 1")
      self.deck.assign_child_resource(dbl_plt_car_1, rails=1)

    with self.assertRaises(ValueError):
      dbl_plt_car_2 = PLT_CAR_L5AC_A00(name="double placed carrier 2")
      self.deck.assign_child_resource(dbl_plt_car_2, rails=2)

    with self.assertRaises(ValueError):
      dbl_plt_car_3 = PLT_CAR_L5AC_A00(name="double placed carrier 3")
      self.deck.assign_child_resource(dbl_plt_car_3, rails=20)

    # Test carrier with same name.
    with self.assertRaises(ValueError):
      same_name_carrier = PLT_CAR_L5AC_A00(name="plate carrier")
      self.deck.assign_child_resource(same_name_carrier, rails=10)
    # Should not raise when replacing.
    self.deck.assign_child_resource(same_name_carrier, rails=10, replace=True)
    # Should not raise when unassinged.
    self.lh.unassign_resource("plate carrier")
    self.deck.assign_child_resource(same_name_carrier, rails=10, replace=True)

    # Test unassigning unassigned resource
    self.lh.unassign_resource("plate carrier")
    with self.assertRaises(ValueError):
      self.lh.unassign_resource("plate carrier")
    with self.assertRaises(ValueError):
      self.lh.unassign_resource("this resource is completely new.")

    # Test invalid rails.
    with self.assertRaises(ValueError):
      self.deck.assign_child_resource(plt_car, rails=-1)
    with self.assertRaises(ValueError):
      self.deck.assign_child_resource(plt_car, rails=42)
    with self.assertRaises(ValueError):
      self.deck.assign_child_resource(plt_car, rails=27)

  def test_get_resource(self):
    tip_car = TIP_CAR_480_A00(name="tip_carrier")
    tip_car[0] = STF_L(name="tip_rack_01")
    plt_car = PLT_CAR_L5AC_A00(name="plate carrier")
    plt_car[0] = Cos_96_DW_1mL(name="aspiration plate")
    self.deck.assign_child_resource(tip_car, rails=1)
    self.deck.assign_child_resource(plt_car, rails=10)

    # Get resource.
    self.assertEqual(self.lh.get_resource("tip_carrier").name, "tip_carrier")
    self.assertEqual(self.lh.get_resource("plate carrier").name, "plate carrier")

    # Get subresource.
    self.assertEqual(self.lh.get_resource("tip_rack_01").name, "tip_rack_01")
    self.assertEqual(self.lh.get_resource("aspiration plate").name, "aspiration plate")

    # Get unknown resource.
    with self.assertRaises(ValueError):
      self.lh.get_resource("unknown resource")

  def test_subcoordinates(self):
    tip_car = TIP_CAR_480_A00(name="tip_carrier")
    tip_car[0] = STF_L(name="tip_rack_01")
    tip_car[3] = HTF_L(name="tip_rack_04")
    plt_car = PLT_CAR_L5AC_A00(name="plate carrier")
    plt_car[0] = Cos_96_DW_1mL(name="aspiration plate")
    plt_car[2] = Cos_96_DW_500ul(name="dispense plate")
    self.deck.assign_child_resource(tip_car, rails=1)
    self.deck.assign_child_resource(plt_car, rails=10)

    # Rails 10 should be left of rails 1.
    self.assertGreater(self.lh.get_resource("plate carrier").get_absolute_location().x,
                       self.lh.get_resource("tip_carrier").get_absolute_location().x)

    # Verified with Hamilton Method Editor.
    # Carriers.
    self.assertEqual(self.lh.get_resource("tip_carrier").get_absolute_location(),
                     Coordinate(100.0, 63.0, 100.0))
    self.assertEqual(self.lh.get_resource("plate carrier").get_absolute_location(),
                     Coordinate(302.5, 63.0, 100.0))

    # Subresources.
    self.assertEqual(
      cast(TipRack, self.lh.get_resource("tip_rack_01")).get_item("A1").get_absolute_location(),
      Coordinate(117.900, 145.800, 164.450))
    self.assertEqual(
      cast(TipRack, self.lh.get_resource("tip_rack_04")).get_item("A1").get_absolute_location(),
      Coordinate(117.900, 433.800, 131.450))

    self.assertEqual(
      cast(TipRack, self.lh.get_resource("aspiration plate")).get_item("A1")
      .get_absolute_location(), Coordinate(320.500, 146.000, 187.150))

  def test_illegal_subresource_assignment_before(self):
    # Test assigning subresource with the same name as another resource in another carrier. This
    # should raise an ValueError when the carrier is assigned to the liquid handler.
    tip_car = TIP_CAR_480_A00(name="tip_carrier")
    tip_car[0] = STF_L(name="sub")
    plt_car = PLT_CAR_L5AC_A00(name="plate carrier")
    plt_car[0] = Cos_96_DW_1mL(name="sub")
    self.deck.assign_child_resource(tip_car, rails=1)
    with self.assertRaises(ValueError):
      self.deck.assign_child_resource(plt_car, rails=10)

  def test_illegal_subresource_assignment_after(self):
    # Test assigning subresource with the same name as another resource in another carrier, after
    # the carrier has been assigned. This should raise an error.
    tip_car = TIP_CAR_480_A00(name="tip_carrier")
    tip_car[0] = STF_L(name="sub")
    plt_car = PLT_CAR_L5AC_A00(name="plate carrier")
    plt_car[0] = Cos_96_DW_1mL(name="ok")
    self.deck.assign_child_resource(tip_car, rails=1)
    self.deck.assign_child_resource(plt_car, rails=10)
    with self.assertRaises(ValueError):
      plt_car[1] = Cos_96_DW_500ul(name="sub")

  def assert_same(self, lh1, lh2):
    """ Assert two liquid handler decks are the same. """
    self.assertEqual(lh1.deck.get_all_resources(), lh2.deck.get_all_resources())

  def test_move_plate_to_site(self):
    plt_car = PLT_CAR_L5AC_A00(name="plate carrier")
    plt_car[0] = plate = Cos_96_DW_1mL(name="plate")
    self.deck.assign_child_resource(plt_car, rails=21)

    self.lh.move_plate(plate, plt_car[2])
    self.assertIsNotNone(plt_car[2].resource)
    self.assertIsNone(plt_car[0].resource)
    self.assertEqual(plt_car[2].resource, self.lh.get_resource("plate"))
    self.assertEqual(plate.get_item("A1").get_absolute_location(),
                     Coordinate(568.000, 338.000, 187.150))

  def test_move_plate_free(self):
    plt_car = PLT_CAR_L5AC_A00(name="plate carrier")
    plt_car[0] = plate = Cos_96_DW_1mL(name="plate")
    self.deck.assign_child_resource(plt_car, rails=1)

    self.lh.move_plate(plate, Coordinate(1000, 1000, 1000))
    self.assertIsNotNone(self.lh.get_resource("plate"))
    self.assertIsNone(plt_car[0].resource)
    self.assertEqual(plate.get_absolute_location(),
      Coordinate(1000, 1000+63, 1000+100))


class TestLiquidHandlerCommands(unittest.TestCase):
  def setUp(self):
    self.maxDiff = None

    self.backend = backends.SaverBackend(num_channels=8)
    self.deck =STARLetDeck()
    self.lh = LiquidHandler(backend=self.backend, deck=self.deck)

    self.tip_rack = STF_L(name="tip_rack")
    self.plate = Cos_96_DW_1mL(name="plate")
    self.deck.assign_child_resource(self.tip_rack, location=Coordinate(0, 0, 0))
    self.deck.assign_child_resource(self.plate, location=Coordinate(100, 100, 0))
    self.lh.setup()

  def get_first_command(self, command) -> Optional[Dict[str, Any]]:
    for sent_command in self.backend.commands_received:
      if sent_command["command"] == command:
        return sent_command
    return None

  def test_offsets_tips(self):
    tips = self.tip_rack["A1"]
    self.lh.pick_up_tips(tips, offsets=Coordinate(x=1, y=1, z=1))
    self.lh.drop_tips(tips, offsets=Coordinate(x=1, y=1, z=1))

    self.assertEqual(self.get_first_command("pick_up_tips"), {
      "command": "pick_up_tips",
      "args": (),
      "kwargs": {
        "use_channels": [0],
        "ops": [
          Pickup(tips[0], tip_type=self.tip_rack.tip_type, offset=Coordinate(x=1, y=1, z=1))]}})
    self.assertEqual(self.get_first_command("drop_tips"), {
      "command": "drop_tips",
      "args": (),
      "kwargs": {
        "use_channels": [0], "ops": [
          Drop(tips[0], tip_type=self.tip_rack.tip_type, offset=Coordinate(x=1, y=1, z=1))]}})

  def test_offsets_asp_disp(self):
    well = self.plate["A1"]
    self.lh.aspirate(well, vols=10, offsets=Coordinate(x=1, y=1, z=1), liquid_classes=None)
    self.lh.dispense(well, vols=10, offsets=Coordinate(x=1, y=1, z=1), liquid_classes=None)

    self.assertEqual(self.get_first_command("aspirate"), {
      "command": "aspirate",
      "args": (),
      "kwargs": {
        "use_channels": [0],
        "ops": [Aspiration(resource=well[0], volume=10, offset=Coordinate(x=1, y=1, z=1))]}})
    self.assertEqual(self.get_first_command("dispense"), {
      "command": "dispense",
      "args": (),
      "kwargs": {
        "use_channels": [0],
        "ops": [Dispense(resource=well[0], volume=10, offset=Coordinate(x=1, y=1, z=1))]}})

  def test_return_tips(self):
    tips = self.tip_rack["A1"]
    self.lh.pick_up_tips(tips)
    self.lh.return_tips()

    self.assertEqual(self.get_first_command("drop_tips"), {
      "command": "drop_tips",
      "args": (),
      "kwargs": {
        "use_channels": [0],
        "ops": [Drop(tips[0], tip_type=self.tip_rack.tip_type)]}})

    with self.assertRaises(RuntimeError):
      self.lh.return_tips()

  def test_return_tips96(self):
    self.lh.pick_up_tips96(self.tip_rack)
    self.lh.return_tips96()

    self.assertEqual(self.get_first_command("drop_tips96"), {
      "command": "drop_tips96",
      "args": (self.tip_rack,),
      "kwargs": {}})

    with self.assertRaises(RuntimeError):
      self.lh.return_tips()

  def test_transfer(self):
    # Simple transfer
    self.lh.transfer(self.plate.get_well("A1"), self.plate["A2"], source_vol=10,
      aspiration_liquid_class=None, dispense_liquid_classes=None)

    self.assertEqual(self.get_first_command("aspirate"), {
      "command": "aspirate",
      "args": (),
      "kwargs": {
        "use_channels": [0],
        "ops": [Aspiration(resource=self.plate.get_item("A1"), volume=10.0)]}})
    self.assertEqual(self.get_first_command("dispense"), {
      "command": "dispense",
      "args": (),
      "kwargs": {
        "use_channels": [0],
        "ops": [Dispense(resource=self.plate.get_item("A2"), volume=10.0)]}})
    self.backend.clear()

    # Transfer to multiple wells
    self.lh.transfer(self.plate.get_well("A1"), self.plate["A1:H1"], source_vol=80,
      aspiration_liquid_class=None, dispense_liquid_classes=None)
    self.assertEqual(self.get_first_command("aspirate"), {
      "command": "aspirate",
      "args": (),
      "kwargs": {
        "use_channels": [0],
        "ops": [Aspiration(resource=self.plate.get_item("A1"), volume=80.0)]}})
    self.assertEqual(self.get_first_command("dispense"), {
      "command": "dispense",
      "args": (),
      "kwargs": {
        "use_channels": [0, 1, 2, 3, 4, 5, 6, 7],
        "ops": [Dispense(resource=well, volume=10.0) for well in self.plate["A1:H1"]]}})
    self.backend.clear()

    # Transfer with ratios
    self.lh.transfer(self.plate.get_well("A1"), self.plate["B1:C1"], source_vol=60, ratios=[2, 1],
      aspiration_liquid_class=None, dispense_liquid_classes=None)
    self.assertEqual(self.get_first_command("aspirate"), {
      "command": "aspirate",
      "args": (),
      "kwargs": {
        "use_channels": [0],
        "ops": [Aspiration(resource=self.plate.get_item("A1"), volume=60.0)]}})
    self.assertEqual(self.get_first_command("dispense"), {
      "command": "dispense",
      "args": (),
      "kwargs": {
        "use_channels": [0, 1],
        "ops": [Dispense(resource=self.plate.get_item("B1"), volume=40.0),
                     Dispense(resource=self.plate.get_item("C1"), volume=20.0)]}})
    self.backend.clear()

    # Transfer with target_vols
    vols: List[float] = [3, 1, 4, 1, 5, 9, 6, 2]
    self.lh.transfer(self.plate.get_well("A1"), self.plate["A1:H1"], target_vols=vols,
      aspiration_liquid_class=None, dispense_liquid_classes=None)
    self.assertEqual(self.get_first_command("aspirate"), {
      "command": "aspirate",
      "args": (),
      "kwargs": {
        "use_channels": [0],
        "ops": [Aspiration(resource=self.plate.get_well("A1"), volume=sum(vols))]}})
    self.assertEqual(self.get_first_command("dispense"), {
      "command": "dispense",
      "args": (),
      "kwargs": {
        "use_channels": [0, 1, 2, 3, 4, 5, 6, 7],
        "ops":
          [Dispense(resource=well, volume=vol) for well, vol in zip(self.plate["A1:H1"], vols)]}})
    self.backend.clear()

    # target_vols and source_vol specified
    with self.assertRaises(TypeError):
      self.lh.transfer(self.plate.get_well("A1"), self.plate["A1:H1"],
        source_vol=100, target_vols=vols)

    # target_vols and ratios specified
    with self.assertRaises(TypeError):
      self.lh.transfer(self.plate.get_well("A1"), self.plate["A1:H1"],
        ratios=[1]*8, target_vols=vols)

  def test_stamp(self):
    # Simple transfer
    self.lh.stamp(self.plate, self.plate, volume=10,
      aspiration_liquid_class=None, dispense_liquid_class=None)

    self.assertEqual(self.get_first_command("aspirate96"), {
      "command": "aspirate96",
      "args": (),
      "kwargs": {"aspiration": Aspiration(resource=self.plate, volume=10.0)}})
    self.assertEqual(self.get_first_command("dispense96"), {
      "command": "dispense96",
      "args": (),
      "kwargs": {"dispense": Dispense(resource=self.plate, volume=10.0)}})
    self.backend.clear()

  def test_tip_tracking_double_pickup(self):
    self.lh.pick_up_tips(self.tip_rack["A1"])

    with self.assertRaises(ChannelHasTipError):
      self.lh.pick_up_tips(self.tip_rack["A2"])

  def test_tip_tracking_empty_drop(self):
    self.tip_rack.get_item("A1").tracker.set_initial_state(has_tip=False)

    with self.assertRaises(ChannelHasNoTipError):
      self.lh.drop_tips(self.tip_rack["A1"])

    self.lh.pick_up_tips(self.tip_rack["A2"])
    self.lh.drop_tips(self.tip_rack["A2"])
    with self.assertRaises(TipSpotHasTipError):
      self.lh.drop_tips(self.tip_rack["A1"])

  def test_tip_tracking_empty_pickup(self):
    self.tip_rack.get_item("A1").tracker.set_initial_state(has_tip=False)

    with self.assertRaises(TipSpotHasNoTipError):
      self.lh.pick_up_tips(self.tip_rack["A1"])

  def test_tip_tracking_full_spot(self):
    self.lh.pick_up_tips(self.tip_rack["A1"])
    with self.assertRaises(TipSpotHasTipError):
      self.lh.drop_tips(self.tip_rack["A2"])

  def test_tip_tracking_double_pickup_single_command(self):
    with self.assertRaises(TipSpotHasNoTipError):
      self.lh.pick_up_tips(self.tip_rack["A1", "A1"])

  def test_disable_tip_tracking(self):
    self.lh.pick_up_tips(self.tip_rack["A1"])

    # Disable tip tracking globally with context manager
    with no_tip_tracking():
      self.lh.pick_up_tips(self.tip_rack["A1"])

    # Disable tip tracking globally and manually
    set_tip_tracking(enabled=False)
    self.lh.pick_up_tips(self.tip_rack["A1"])
    set_tip_tracking(enabled=True)

    # Disable tip tracking for a single tip rack
    self.tip_rack.get_item("A1").tracker.disable()
    self.lh.pick_up_tips(self.tip_rack["A1"])
    self.tip_rack.get_item("A1").tracker.enable()

  def test_discard_tips(self):
    self.lh.pick_up_tips(self.tip_rack["A1", "B1", "C1", "D1"], use_channels=[0, 1, 3, 4])
    self.lh.discard_tips()
    offsets = self.deck.get_trash_area().get_2d_center_offsets(n=4)

    self.assertEqual(self.get_first_command("drop_tips"), {
      "command": "drop_tips",
      "args": (),
      "kwargs": {
        "use_channels": [0, 1, 3, 4],
        "ops": [
          Drop(self.deck.get_trash_area(), tip_type=self.tip_rack.tip_type, offset=offsets[3]),
          Drop(self.deck.get_trash_area(), tip_type=self.tip_rack.tip_type, offset=offsets[2]),
          Drop(self.deck.get_trash_area(), tip_type=self.tip_rack.tip_type, offset=offsets[1]),
          Drop(self.deck.get_trash_area(), tip_type=self.tip_rack.tip_type, offset=offsets[0]),
        ]}})

    # test tip tracking
    with self.assertRaises(RuntimeError):
      self.lh.discard_tips()


if __name__ == "__main__":
  unittest.main()
