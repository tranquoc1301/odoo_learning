from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestEstateProperty(TransactionCase):
    def setUp(self):
        super().setUp()
        self.property = self.env["estate.property"].create(
            {
                "name": "Test Property",
                "description": "This is a test property.",
                "expected_price": 100000,
                "bedrooms": 3,
                "living_area": 50,
                "garden": True,
                "garden_area": 20,
                "garden_orientation": "north",
                "garage": True,
            }
        )
        self.partner = self.env["res.partner"].create(
            {
                "name": "Tran Quoc",
            }
        )

    def test_property_name(self):
        self.assertEqual(self.property.name, "Test Property")

    def test_property_expected_price(self):
        self.assertEqual(self.property.expected_price, 100000)

    def test_property_initial_state(self):
        self.assertEqual(self.property.state, "new")

    def test_write_update_property(self):
        self.property.write({"name": "Updated Test Property"})
        self.assertEqual(self.property.name, "Updated Test Property")

    def test_total_area_computation(self):
        self.assertEqual(self.property.total_area, 70)

    def test_action_cancel(self):
        self.property.action_cancel()
        self.assertEqual(self.property.state, "cancelled")

    def test_cannot_cancel_sold_property(self):
        self.property.action_sold()
        with self.assertRaises(UserError):
            self.property.action_cancel()

    def test_cannot_sell_cancelled_property(self):
        self.property.action_cancel()
        with self.assertRaises(UserError):
            self.property.action_sold()
