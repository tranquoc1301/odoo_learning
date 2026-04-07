from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestPropertyOffer(TransactionCase):
    def setUp(self):
        super().setUpClass()
        self.property = self.env["estate.property"].create(
            {
                "name": "Test Property",
                "description": "This is a test property.",
                "expected_price": 100000.0,
                "bedrooms": 3,
                "living_area": 100,
                "garden_area": 50,
            }
        )
        self.partner = self.env["res.partner"].create(
            {
                "name": "Tran Van A",
            }
        )

    def test_create_offer_changes_property_state(self):
        self.env["estate.property.offer"].create(
            {
                "price": 98000.0,
                "partner_id": self.partner.id,
                "property_id": self.property.id,
            }
        )
        self.assertEqual(self.property.state, "offer_received")

    def test_create_accepted_offer_changes_property_state(self):
        offer = self.env["estate.property.offer"].create(
            {
                "price": 98000.0,
                "partner_id": self.partner.id,
                "property_id": self.property.id,
                "status": "accepted",
            }
        )
        self.assertEqual(self.property.state, "offer_accepted")
        self.assertEqual(self.property.selling_price, offer.price)
        self.assertEqual(self.property.buyer_id, self.partner)

    def test_action_accept_updates_property(self):
        offer = self.env["estate.property.offer"].create(
            {
                "price": 275000.0,
                "partner_id": self.partner.id,
                "property_id": self.property.id,
            }
        )
        offer.action_accept()
        self.assertEqual(self.property.selling_price, 275000.0)
        self.assertEqual(self.property.buyer_id, self.partner)
        self.assertEqual(self.property.state, "offer_accepted")

    def test_action_refuse(self):
        """Test refusing an offer sets status to refuse."""
        offer = self.env["estate.property.offer"].create(
            {
                "price": 260000.0,
                "partner_id": self.partner.id,
                "property_id": self.property.id,
            }
        )
        offer.action_refuse()
        self.assertEqual(offer.status, "refused")

    def test_cannot_accept_already_accepted(self):
        offer = self.env["estate.property.offer"].create(
            {
                "price": 250000.0,
                "status": "accepted",
                "partner_id": self.partner.id,
                "property_id": self.property.id,
            }
        )
        with self.assertRaises(UserError):
            offer.action_accept()

    def test_cannot_accept_second_offer(self):
        second_partner = self.env["res.partner"].create(
            {
                "name": "Bob Competitor",
            }
        )
        first_offer = self.env["estate.property.offer"].create(
            {
                "price": 250000.0,
                "partner_id": self.partner.id,
                "property_id": self.property.id,
            }
        )
        first_offer.action_accept()
        second_offer = self.env["estate.property.offer"].create(
            {
                "price": 260000.0,
                "partner_id": second_partner.id,
                "property_id": self.property.id,
            }
        )
        with self.assertRaises(UserError):
            second_offer.action_accept()
