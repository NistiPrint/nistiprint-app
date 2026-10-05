import unittest
from unittest.mock import patch, MagicMock
from nistiprint_shared.services.marketplace_logistics_facts import normalize_sla, meli_dispatch_timestamp
from nistiprint_shared.services.platform_drivers import mercadolivre as driver


class LogisticsFactsTest(unittest.TestCase):
    def test_sla_object_list_empty_and_failure(self):
        value = {'expected_date': '2026-10-02T13:00:00-03:00'}
        self.assertEqual(normalize_sla(value), value)
        self.assertEqual(normalize_sla([value]), value)
        for raw in ([], None, {'error': '429'}, 'bad'):
            self.assertEqual(normalize_sla(raw), {})

    def test_ready_to_print_and_date_closed_never_confirm_collection(self):
        detail = {'order': {'date_closed': '2026-10-02T09:00:00-03:00'}, 'shipment': {
            'status': 'ready_to_ship', 'substatus': 'ready_to_print', 'date_shipped': '2026-10-02T14:00:00-03:00'}}
        self.assertIsNone(meli_dispatch_timestamp(detail))

    def test_departure_without_physical_timestamp_stays_unknown(self):
        for substatus in ('picked_up', 'authorized_by_carrier', 'in_hub'):
            self.assertIsNone(meli_dispatch_timestamp({'order': {'date_closed': '2026-10-02T09:00:00-03:00'},
                'shipment': {'status': 'ready_to_ship', 'substatus': substatus}}))

    def test_first_physical_event_is_used_not_last_update(self):
        shipment = {'status': 'shipped', 'last_updated': '2026-10-02T20:00:00-03:00', '_history': [
            {'status': 'ready_to_ship', 'substatus': 'ready_to_print', 'date': '2026-10-02T11:00:00-03:00'},
            {'status': 'shipped', 'date': '2026-10-02T15:00:00-03:00'},
            {'status': 'ready_to_ship', 'substatus': 'picked_up', 'date': '2026-10-02T14:00:00-03:00'}]}
        self.assertEqual(meli_dispatch_timestamp({'shipment': shipment}), '2026-10-02T14:00:00-03:00')

    def test_sla_driver_accepts_array_response(self):
        response = MagicMock(status_code=200, headers={})
        response.json.return_value = [{'expected_date': '2026-10-02T13:00:00-03:00'}]
        with patch.object(driver.requests, 'get', return_value=response):
            result = driver.get_shipment_sla({'access_token': 'local'}, '123')
        self.assertEqual(result['expected_date'], '2026-10-02T13:00:00-03:00')

    def test_shipment_driver_gets_history_only_after_departure(self):
        response = MagicMock(status_code=200, headers={})
        response.json.return_value = {'id': 123, 'status': 'ready_to_ship', 'substatus': 'picked_up'}
        with patch.object(driver.requests, 'get', return_value=response), patch.object(driver, 'get_shipment_history',
             return_value={'history': [{'status': 'shipped', 'date': '2026-10-02T14:00:00-03:00'}]}) as history:
            result = driver.get_shipment({'access_token': 'local'}, '123')
        history.assert_called_once()
        self.assertEqual(meli_dispatch_timestamp({'shipment': result}), '2026-10-02T14:00:00-03:00')
