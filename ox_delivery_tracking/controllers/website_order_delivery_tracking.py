# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class Tracking(http.Controller):
    """Class representing Tracking"""

    @http.route('/tracking/details', type='http', auth="public", website=True,
                csrf=False)
    def get_track_details(self):
        """Track data"""
        return request.render(
            'ox_delivery_tracking.trackingTemplate')

    @http.route(['/tracking/details/update'], type='json', auth="public",
                website=True)
    def input_data_processing(self, **post):
        """Fetch input json data sent from js - integrated with FedEx API"""
        input_data = post.get('input_data', '')
        search_type = post.get('search_type', 'tracking')  # tracking, order, picking
        # Convert to string if it's not already (handles int, float, etc.)
        search_value = str(input_data).strip() if input_data else ''
        if not search_value:
            return []
        
        picking = False
        tracking_number = ''
        
        # Search based on type - use sudo() for public access
        if search_type == 'order':
            # Search by Sale Order number
            sale_order = request.env['sale.order'].sudo().search([
                ('name', '=', search_value)
            ], limit=1)
            if sale_order:
                # Get pickings related to this sale order (prefer pickings with tracking)
                picking = request.env['stock.picking'].sudo().search([
                    ('sale_id', '=', sale_order.id),
                    ('state', '!=', 'cancel'),
                    '|',
                    ('carrier_tracking_ref', '!=', False),
                    ('fedex_tracking_number', '!=', False)
                ], order='create_date desc', limit=1)
                # If no picking with tracking, get any picking
                if not picking:
                    picking = request.env['stock.picking'].sudo().search([
                        ('sale_id', '=', sale_order.id),
                        ('state', '!=', 'cancel')
                    ], order='create_date desc', limit=1)
                if picking:
                    tracking_number = picking.carrier_tracking_ref or picking.fedex_tracking_number or ''
        elif search_type == 'picking':
            # Search by Picking number
            picking = request.env['stock.picking'].sudo().search([
                ('name', '=', search_value)
            ], limit=1)
            if picking:
                tracking_number = picking.carrier_tracking_ref or picking.fedex_tracking_number or ''
        else:
            # Default: Search by tracking number (carrier_tracking_ref or fedex_tracking_number)
            picking = request.env['stock.picking'].sudo().search([
                '|',
                ('carrier_tracking_ref', '=', search_value),
                ('fedex_tracking_number', '=', search_value)
            ], limit=1)
            if picking:
                tracking_number = search_value
        
        if not picking:
            # If we have a tracking number, try to fetch from FedEx API
            if tracking_number:
                try:
                    FedexAPI = request.env['fedex.api'].sudo()
                    fedex_result = FedexAPI.track_shipment(tracking_number)
                    
                    if fedex_result and fedex_result.get('output'):
                        # Parse FedEx response using StockPicking model method
                        # Get any picking record to use the instance method
                        temp_picking = request.env['stock.picking'].sudo().search([], limit=1)
                        if temp_picking and hasattr(temp_picking, '_fedex_parse_result'):
                            parsed = temp_picking._fedex_parse_result(fedex_result)
                        else:
                            parsed = {}
                        
                        # Extract scan events from FedEx result
                        scan_events = []
                        try:
                            result_data = fedex_result.get('output', {}).get('completeTrackResults', [{}])[0].get('trackResults', [{}])[0]
                            scan_events_raw = result_data.get('scanEvents', [])
                            scan_events = scan_events_raw[:10] if scan_events_raw else []  # Limit to 10 most recent
                        except:
                            scan_events = []
                        
                        # Extract additional shipment facts
                        weight_lb = parsed.get('weight_lb') or 0
                        weight_kg = parsed.get('weight_kg') or 0
                        actual_pickup = parsed.get('actual_pickup') or ''
                        standard_transit = parsed.get('std_transit_end') or ''
                        # Special handlings is a list of strings
                        special_handlings_list = parsed.get('special_handlings') or []
                        special_handlings = special_handlings_list if isinstance(special_handlings_list, list) else []
                        
                        # Return FedEx tracking data
                        return [{
                            'tracking_number': tracking_number,
                            'status': parsed.get('status') or 'In Transit',
                            'status_description': parsed.get('status_description') or '',
                            'latest_event': parsed.get('latest_scan_event') or '',
                            'latest_scan_date': parsed.get('latest_scan_date') or '',
                            'latest_scan_city': parsed.get('latest_scan_city') or '',
                            'latest_scan_state': parsed.get('latest_scan_state') or '',
                            'delivery_date': parsed.get('delivery_date') or '',
                            'actual_delivery': parsed.get('actual_delivery') or '',
                            'origin_city': parsed.get('origin_city') or '',
                            'origin_state': parsed.get('origin_state') or '',
                            'destination_city': parsed.get('destination_city') or '',
                            'destination_state': parsed.get('destination_state') or '',
                            'service_type': parsed.get('service_type') or '',
                            'service_desc': parsed.get('service_desc') or '',
                            'weight_lb': weight_lb,
                            'weight_kg': weight_kg,
                            'actual_pickup': actual_pickup,
                            'standard_transit': standard_transit,
                            'special_handlings': special_handlings,
                            'scan_events': scan_events,
                            'carrier': 'FedEx',
                            'from_fedex_api': True,
                        }]
                except Exception as e:
                    return []
            else:
                # No picking found and no tracking number to search FedEx API
                return []
        
        # Parse scan events from stored JSON if available
        scan_events = []
        if picking.fedex_scan_events_json:
            try:
                import json
                scan_events = json.loads(picking.fedex_scan_events_json)
            except Exception as e:
                scan_events = []
        
        # Extract latest event info from scan events (most recent is first)
        latest_event_desc = picking.tracking_last_event or ''
        latest_scan_date_str = ''
        latest_scan_city = ''
        latest_scan_state = ''
        
        if scan_events and len(scan_events) > 0:
            # Get most recent scan event (first in list)
            latest_event_data = scan_events[0]
            
            if isinstance(latest_event_data, dict):
                # Extract event description
                if not latest_event_desc:
                    latest_event_desc = latest_event_data.get('eventDescription') or latest_event_data.get('eventType') or ''
                
                # Extract date
                event_date = latest_event_data.get('date') or latest_event_data.get('eventDate') or ''
                if event_date:
                    try:
                        from datetime import datetime
                        # Try to parse and format the date
                        if isinstance(event_date, str):
                            # Try different date formats
                            for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
                                try:
                                    dt = datetime.strptime(event_date.split('.')[0], fmt)
                                    latest_scan_date_str = dt.strftime('%Y-%m-%d %H:%M:%S')
                                    break
                                except:
                                    continue
                            if not latest_scan_date_str:
                                latest_scan_date_str = event_date
                        else:
                            latest_scan_date_str = str(event_date)
                    except:
                        latest_scan_date_str = str(event_date) if event_date else ''
                
                # Extract location
                scan_location = latest_event_data.get('scanLocation', {})
                if isinstance(scan_location, dict):
                    latest_scan_city = scan_location.get('city', '') or ''
                    latest_scan_state = scan_location.get('stateOrProvinceCode', '') or ''
        
        # Fallback to picking fields if scan events don't have the data
        if not latest_event_desc:
            latest_event_desc = picking.tracking_last_event or ''
        if not latest_scan_date_str and picking.tracking_last_date:
            latest_scan_date_str = picking.tracking_last_date.strftime('%Y-%m-%d %H:%M:%S')
        if not latest_scan_city:
            latest_scan_city = picking.fedex_last_dest_city or picking.fedex_delivery_city or ''
        if not latest_scan_state:
            latest_scan_state = picking.fedex_last_dest_state or picking.fedex_delivery_state or ''
        
        # Try to get status_description from tracking_raw if available
        status_description = ''
        if picking.tracking_raw:
            try:
                import json
                raw_data = json.loads(picking.tracking_raw)
                # Try to extract status description from raw data
                if raw_data.get('output'):
                    track_results = raw_data.get('output', {}).get('completeTrackResults', [{}])
                    if track_results:
                        track_result = track_results[0].get('trackResults', [{}])[0]
                        latest_status_detail = track_result.get('latestStatusDetail', {})
                        status_description = latest_status_detail.get('description', '')
            except:
                pass
        
        # If picking found, return stored FedEx data or basic info
        # Ensure all string fields are explicitly set to empty string (not None) to avoid undefined in JSON
        # For dropship pickings, use sale_id.name instead of origin (which shows PO number)
        origin_value = ''
        if picking.picking_type_code == 'dropship' and picking.sale_id:
            origin_value = picking.sale_id.name or ''
        else:
            origin_value = picking.origin or ''
        result = {
            'picking_name': picking.name or '',
            'origin': origin_value,
            'carrier': picking.carrier_id.name if picking.carrier_id else 'FedEx',
            'tracking_number': tracking_number or '',
            'status': picking.tracking_status or '',
            'status_description': status_description or '',
            'latest_event': latest_event_desc or '',
            'latest_scan_date': latest_scan_date_str or '',
            'latest_scan_city': latest_scan_city or '',
            'latest_scan_state': latest_scan_state or '',
            'delivery_date': picking.fedex_actual_delivery.strftime('%Y-%m-%d %H:%M:%S') if picking.fedex_actual_delivery else '',
            'actual_delivery': picking.fedex_actual_delivery.strftime('%Y-%m-%d %H:%M:%S') if picking.fedex_actual_delivery else '',
            'delivered': bool(picking.fedex_delivered),
            'origin_city': picking.fedex_origin_city or '',
            'origin_state': picking.fedex_origin_state or '',
            'destination_city': picking.fedex_destination_city or '',
            'destination_state': picking.fedex_destination_state or '',
            'service_type': picking.fedex_service_type or '',
            'service_desc': picking.fedex_service_desc or '',
            'delivery_city': picking.fedex_delivery_city or '',
            'delivery_state': picking.fedex_delivery_state or '',
            'received_by': picking.fedex_delivery_received_by or '',
            'weight_lb': float(picking.fedex_weight_lb) if picking.fedex_weight_lb else 0.0,
            'weight_kg': float(picking.fedex_weight_kg) if picking.fedex_weight_kg else 0.0,
            'actual_pickup': picking.fedex_actual_pickup.strftime('%Y-%m-%d %H:%M:%S') if picking.fedex_actual_pickup else '',
            'standard_transit': picking.fedex_standard_transit_end.strftime('%Y-%m-%d %H:%M:%S') if picking.fedex_standard_transit_end else '',
            'special_handlings': picking.fedex_special_handlings.split('\n') if picking.fedex_special_handlings else [],
            'scan_events': scan_events,
            'from_fedex_api': False,
        }
        
        # If no FedEx data stored, try to fetch from API
        if not picking.tracking_status and not picking.fedex_tracking_number:
            try:
                FedexAPI = request.env['fedex.api'].sudo()
                fedex_result = FedexAPI.track_shipment(tracking_number)
                
                if fedex_result and fedex_result.get('output'):
                    # Use the picking record itself to parse
                    parsed = picking._fedex_parse_result(fedex_result) if hasattr(picking, '_fedex_parse_result') else {}
                    
                    # Extract scan events from FedEx result
                    scan_events = []
                    try:
                        import json
                        result_data = fedex_result.get('output', {}).get('completeTrackResults', [{}])[0].get('trackResults', [{}])[0]
                        scan_events_raw = result_data.get('scanEvents', [])
                        scan_events = scan_events_raw[:10] if scan_events_raw else []  # Limit to 10 most recent
                    except:
                        scan_events = []
                    
                    # Extract additional shipment facts
                    weight_lb = parsed.get('weight_lb') or 0
                    weight_kg = parsed.get('weight_kg') or 0
                    actual_pickup = parsed.get('actual_pickup') or ''
                    standard_transit = parsed.get('std_transit_end') or ''
                    # Special handlings is a list of strings
                    special_handlings_list = parsed.get('special_handlings') or []
                    special_handlings = special_handlings_list if isinstance(special_handlings_list, list) else []
                    
                    # Update with API data - ensure all fields are included
                    result.update({
                        'status': parsed.get('status') or result.get('status') or 'In Transit',
                        'status_description': parsed.get('status_description') or result.get('status_description') or '',
                        'latest_event': parsed.get('latest_scan_event') or result.get('latest_event') or '',
                        'latest_scan_date': parsed.get('latest_scan_date') or result.get('latest_scan_date') or '',
                        'latest_scan_city': parsed.get('latest_scan_city') or result.get('latest_scan_city') or '',
                        'latest_scan_state': parsed.get('latest_scan_state') or result.get('latest_scan_state') or '',
                        'delivery_date': parsed.get('delivery_date') or parsed.get('actual_delivery') or result.get('delivery_date') or '',
                        'actual_delivery': parsed.get('actual_delivery') or result.get('actual_delivery') or '',
                        'origin_city': parsed.get('origin_city') or result.get('origin_city') or '',
                        'origin_state': parsed.get('origin_state') or result.get('origin_state') or '',
                        'destination_city': parsed.get('destination_city') or result.get('destination_city') or '',
                        'destination_state': parsed.get('destination_state') or result.get('destination_state') or '',
                        'delivery_city': parsed.get('delivery_city') or result.get('delivery_city') or '',
                        'delivery_state': parsed.get('delivery_state') or result.get('delivery_state') or '',
                        'received_by': parsed.get('delivery_received_by') or result.get('received_by') or '',
                        'service_type': parsed.get('service_type') or result.get('service_type') or '',
                        'service_desc': parsed.get('service_desc') or result.get('service_desc') or '',
                        'weight_lb': weight_lb or result.get('weight_lb') or 0,
                        'weight_kg': weight_kg or result.get('weight_kg') or 0,
                        'actual_pickup': actual_pickup or result.get('actual_pickup') or '',
                        'standard_transit': standard_transit or result.get('standard_transit') or '',
                        'special_handlings': special_handlings or result.get('special_handlings') or [],
                        'scan_events': scan_events or result.get('scan_events') or [],
                        'from_fedex_api': True,
                    })
            except Exception as e:
                pass
        
        return [result]

    @http.route('/tracking/details/edit', type='json', auth="public",
                website=False,
                csrf=False, methods=['GET', 'POST'])
    def track_data_edit(self, **post):
        """Edit tracking data"""
        tracking_api = request.env['ir.config_parameter'].sudo().get_param(
            'stock.delivery_tracking_api_key')
        track_data = request.env['stock.picking'].sudo().search(
            [('carrier_tracking_ref', '=', post.get('tracking_number'))])
        if track_data and post.get(
                'api_key') == tracking_api:
            track_data.write({
                'tracking_status': post.get('tracking_status'),
            })
            return track_data.tracking_status
        else:
            return []
