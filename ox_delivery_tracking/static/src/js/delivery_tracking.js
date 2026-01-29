/** @odoo-module **/
import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.OrderTrackingWidget = publicWidget.Widget.extend({
    // Bind the widget to the #deliveryTrackingForm element
		selector: '.TrackingTemplates',

    // Handler for the delivery tracking form submit event
		events: {
			'click #trackingInputBtn': '_onDeliveryTracking',
			'click #TrackingUpdate': '_onDeliveryTrackingUpdate',
			'input #trackingNumberInput': '_onTrackingNumberInput',
			'change #searchType': '_onSearchTypeChange',
			'click #backToSearchBtn a': '_onBackToSearch',
			'click .view-travel-history': '_onViewTravelHistory',
			'click #travelHistoryBackBtn': '_onCloseTravelHistory',
		},

        _onTrackingNumberInput:function(ev){
		if(!this.$el.find("#trackingNumberInput").val()){
		this.$el.find("#trackedTableDetails").hide();
		this.$el.find("#trackedTimelineDetails").hide();
		}
		},

		_onSearchTypeChange: function(ev) {
			let self = this;
			let searchType = self.$el.find("#searchType").val();
			let placeholder = '';
			
			switch(searchType) {
				case 'order':
					placeholder = 'Enter Order Number (e.g., P00016)';
					break;
				case 'picking':
					placeholder = 'Enter Delivery Number (e.g., INT/00016)';
					break;
				default:
					placeholder = 'Enter Tracking Number';
			}
			
			self.$el.find("#trackingNumberInput").attr('placeholder', placeholder);
		},

		_onDeliveryTracking: function(ev) {
			let self = this
			//     Submit event handler for delivery tracking form
			self.$el.find('#deliveryTrackingForm').submit(function(e) {

				e.preventDefault();

				// Get the search value and type from the input field
				var searchValue = self.$el.find("#trackingNumberInput").val();
				var searchType = self.$el.find("#searchType").val() || 'tracking';
				// Call the server-side controller to update tracking details
				rpc("/tracking/details/update", {
                    'input_data': searchValue,
                    'search_type': searchType,
                 }).then(function(data) {
                    let noRecordsMsg = self.$el.find('#noRecordsMsg');
					// Check if data exists
					if (data.length > 0) {
						let trackingData = data[0];
						
						// Hide search form and show back button
						self.$el.find("#searchFormContainer").slideUp(300);
						self.$el.find("#backToSearchBtn").fadeIn(300);
						
						// Show results
						self.$el.find("#trackedTableDetails").show();
						self.$el.find("#trackedTimelineDetails").show();
						
						// Format dates
						function formatDate(dateStr) {
							if (!dateStr) return 'N/A';
							try {
								let date = new Date(dateStr);
								return date.toLocaleString();
							} catch(e) {
								return dateStr;
							}
						}
						
						// Format date for timeline (shorter format)
						function formatTimelineDate(dateStr) {
							if (!dateStr) return '';
							try {
								let date = new Date(dateStr);
								let month = date.getMonth() + 1;
								let day = date.getDate();
								let year = date.getFullYear().toString().slice(-2);
								let hours = date.getHours();
								let minutes = date.getMinutes();
								let ampm = hours >= 12 ? 'PM' : 'AM';
								hours = hours % 12;
								hours = hours ? hours : 12;
								minutes = minutes < 10 ? '0' + minutes : minutes;
								return `${month}/${day}/${year} ${hours}:${minutes} ${ampm}`;
							} catch(e) {
								return dateStr;
							}
						}
						
						// Build detailed tracking information - use latest scan event from timeline
						let statusHtml = '';
						// Priority: first scan event (most recent) > latest_event > status > default
						let latestStatusText = '';
						
						// Check scan events first (most recent event is first in array, same as timeline)
						if (trackingData.scan_events && Array.isArray(trackingData.scan_events) && trackingData.scan_events.length > 0) {
							let mostRecentEvent = trackingData.scan_events[0];
							// Use same logic as timeline: eventDescription || eventType
							latestStatusText = mostRecentEvent.eventDescription || mostRecentEvent.eventType || '';
						}
						
						// Fallback to latest_event if no scan events
						if (!latestStatusText && trackingData.latest_event) {
							latestStatusText = trackingData.latest_event;
						}
						
						// Fallback to status if still no text
						if (!latestStatusText && trackingData.status) {
							latestStatusText = trackingData.status;
						}
						
						// Default if nothing available
						if (!latestStatusText) {
							latestStatusText = 'In Transit';
						}
						
						// Format status HTML with checkmark if delivered
						if (trackingData.delivered || latestStatusText.toLowerCase().includes('delivered')) {
							statusHtml = '<span style="color: #28a745; font-weight: bold;">✓</span> <strong style="color: #000;">' + latestStatusText + '</strong>';
						} else {
							statusHtml = latestStatusText;
						}
						
						// Display the tracking details in a comprehensive table
						let html = `
                    <div class="card shadow-sm mb-4">
                        <div class="card-header bg-primary text-white">
                            <h5 class="mb-0"><i class="fa fa-truck"></i> Tracking Information</h5>
                        </div>
                        <div class="card-body">
                            <table class="table table-bordered">
                                <tbody>
                                    <tr>
                                        <th width="30%">Tracking Number</th>
                                        <td><strong>${trackingData.tracking_number || 'N/A'}</strong></td>
                                    </tr>
                                    ${trackingData.picking_name ? `
                                    <tr>
                                        <th>Picking Reference</th>
                                        <td>${trackingData.picking_name}</td>
                                    </tr>
                                    ` : ''}
                                    ${trackingData.origin ? `
                                    <tr>
                                        <th>Sale Order</th>
                                        <td>${trackingData.origin}</td>
                                    </tr>
                                    ` : ''}
                                    <tr>
                                        <th>Carrier</th>
                                        <td>${trackingData.carrier || 'FedEx'}</td>
                                    </tr>
                                    <tr>
                                        <th>Status</th>
                                        <td>${statusHtml}</td>
                                    </tr>
                                    ${trackingData.status_description ? `
                                    <tr>
                                        <th>Status Description</th>
                                        <td>${trackingData.status_description}</td>
                                    </tr>
                                    ` : ''}
                                    ${trackingData.latest_event ? `
                                    <tr>
                                        <th>Latest Event</th>
                                        <td>${trackingData.latest_event}</td>
                                    </tr>
                                    ` : ''}
                                    ${trackingData.latest_scan_date ? `
                                    <tr>
                                        <th>Last Update</th>
                                        <td>${formatDate(trackingData.latest_scan_date)}</td>
                                    </tr>
                                    ` : ''}
                                    ${trackingData.latest_scan_city || trackingData.latest_scan_state ? `
                                    <tr>
                                        <th>Last Location</th>
                                        <td>${(trackingData.latest_scan_city || '') + (trackingData.latest_scan_state ? ', ' + trackingData.latest_scan_state : '')}</td>
                                    </tr>
                                    ` : ''}
                                    ${trackingData.delivery_date || trackingData.actual_delivery ? `
                                    <tr>
                                        <th>Delivery Date</th>
                                        <td>${formatDate(trackingData.actual_delivery || trackingData.delivery_date)}</td>
                                    </tr>
                                    ` : ''}
                                    ${trackingData.received_by ? `
                                    <tr>
                                        <th>Received By</th>
                                        <td>${trackingData.received_by}</td>
                                    </tr>
                                    ` : ''}
                                    ${trackingData.service_type || trackingData.service_desc ? `
                                    <tr>
                                        <th>Service Type</th>
                                        <td>${trackingData.service_desc || trackingData.service_type || 'N/A'}</td>
                                    </tr>
                                    ` : ''}
                                    ${(trackingData.origin_city || trackingData.origin_state) ? `
                                    <tr>
                                        <th>Origin</th>
                                        <td>${(trackingData.origin_city || '') + (trackingData.origin_state ? ', ' + trackingData.origin_state : '')}</td>
                                    </tr>
                                    ` : ''}
                                    ${(trackingData.destination_city || trackingData.destination_state) ? `
                                    <tr>
                                        <th>Destination</th>
                                        <td>${(trackingData.destination_city || '') + (trackingData.destination_state ? ', ' + trackingData.destination_state : '')}</td>
                                    </tr>
                                    ` : ''}
                                    ${(trackingData.delivery_city || trackingData.delivery_state) ? `
                                    <tr>
                                        <th>Delivery Location</th>
                                        <td>${(trackingData.delivery_city || '') + (trackingData.delivery_state ? ', ' + trackingData.delivery_state : '')}</td>
                                    </tr>
                                    ` : ''}
                                    ${trackingData.from_fedex_api ? `
                                    <tr>
                                        <th>Data Source</th>
                                        <td><span class="badge bg-info">Live FedEx API</span></td>
                                    </tr>
                                    ` : ''}
                                </tbody>
                            </table>
                        </div>
                    </div>
                `;
						self.$el.find("#trackedTableDetails").html(html);
						
						// Build timeline on right side
						let timelineHtml = self._buildTimeline(trackingData, formatTimelineDate);
						self.$el.find("#trackedTimelineDetails").html(timelineHtml);
						
						self.$el.find('#noRecordsMsg').hide();
					}

					// If no data is returned, display an alert and hide the table
					if (data.length <= 0) {
						self.$el.find('#NoRecordsApiKey').modal('show');
						self.$el.find("#trackedTableDetails").hide();
						self.$el.find("#trackedTimelineDetails").hide();
						// Keep search form visible if no results
						self.$el.find("#searchFormContainer").show();
						self.$el.find("#backToSearchBtn").hide();
					}
				});
			});
		},

		_onBackToSearch: function(ev) {
			let self = this;
			ev.preventDefault();
			// Hide results and back button
			self.$el.find("#trackedTableDetails").hide();
			self.$el.find("#trackedTimelineDetails").hide();
			self.$el.find("#backToSearchBtn").fadeOut(300);
			// Show search form
			self.$el.find("#searchFormContainer").slideDown(300);
			// Clear input
			self.$el.find("#trackingNumberInput").val('');
		},

		_buildTimeline: function(trackingData, formatDate) {
			let self = this;
			let timelineItems = [];
			let latestEventIndex = -1; // Track index of latest event
			
			// Process scan events if available
			if (trackingData.scan_events && Array.isArray(trackingData.scan_events) && trackingData.scan_events.length > 0) {
				trackingData.scan_events.forEach((event, index) => {
					let eventDesc = event.eventDescription || event.eventType || '';
					let eventDate = event.date || '';
					let scanLocation = event.scanLocation || {};
					let city = scanLocation.city || '';
					let state = scanLocation.stateOrProvinceCode || '';
					let location = city + (city && state ? ', ' : '') + state;
					
					// Determine status
					let status = 'completed';
					let isLatest = false;
					if (index === 0) {
						status = 'active'; // Most recent event
						isLatest = true;
						latestEventIndex = timelineItems.length; // Store index for latest event
					}
					
					// Check if it's a delivery event
					if (eventDesc && (eventDesc.toLowerCase().includes('delivered') || eventDesc.toLowerCase().includes('delivery'))) {
						status = 'active';
					}
					
					timelineItems.push({
						type: 'event',
						title: eventDesc || 'Package Update',
						location: location || 'Location not available',
						date: formatDate(eventDate),
						status: status,
						description: '',
						isLatestEvent: isLatest
					});
				});
			} else {
				// Fallback: Use latest event if scan events not available
				if (trackingData.latest_event) {
					latestEventIndex = timelineItems.length; // Mark as latest event
					timelineItems.push({
						type: 'event',
						title: trackingData.latest_event,
						location: `${trackingData.latest_scan_city || ''}${trackingData.latest_scan_city && trackingData.latest_scan_state ? ', ' : ''}${trackingData.latest_scan_state || ''}`,
						date: formatDate(trackingData.latest_scan_date),
						status: 'active',
						description: '',
						isLatestEvent: true
					});
				}
				
				// Add status milestones
				if (trackingData.status) {
					let statusLower = trackingData.status.toLowerCase();
					if (statusLower.includes('picked') || statusLower.includes('package')) {
						timelineItems.push({
							type: 'milestone',
							title: 'WE HAVE YOUR PACKAGE',
							location: trackingData.origin_city ? `${trackingData.origin_city}, ${trackingData.origin_state || ''}` : '',
							date: '',
							status: 'completed',
							description: ''
						});
					}
					if (statusLower.includes('transit') || statusLower.includes('way')) {
						timelineItems.push({
							type: 'milestone',
							title: 'ON THE WAY',
							location: '',
							date: '',
							status: 'completed',
							description: ''
						});
					}
					if (statusLower.includes('out for delivery')) {
						timelineItems.push({
							type: 'milestone',
							title: 'OUT FOR DELIVERY',
							location: '',
							date: '',
							status: 'active',
							description: ''
						});
					}
				}
			}
			
			// Build timeline HTML
			let timelineHtml = `
				<div class="timeline-card">
					<div class="timeline-header">
						<div class="tracking-id">
							TRACKING ID: ${trackingData.tracking_number || 'N/A'}
						</div>
						<div class="timeline-actions">
							<i class="fa fa-pencil"></i>
							<i class="fa fa-star-o"></i>
						</div>
					</div>
					<div class="tracking-timeline">
			`;
			
			timelineItems.forEach((item, index) => {
				let isLast = index === timelineItems.length - 1;
				let isLatestEvent = item.isLatestEvent === true;
				
				// For latest event: create layered design with circle, square, and box icon
				let markerContent = '';
				if (isLatestEvent) {
					markerContent = `
						<div class="timeline-marker">
							<div class="timeline-marker-square">
								<i class="fa fa-cube timeline-marker-box"></i>
							</div>
						</div>
					`;
				} else {
					markerContent = '<div class="timeline-marker"></div>';
				}
				
				timelineHtml += `
					<div class="timeline-item ${item.status} ${isLatestEvent ? 'latest-event' : ''}">
						${markerContent}
						<div class="timeline-content">
							<div class="timeline-title">${item.title}</div>
							${item.location ? `<div class="timeline-location">${item.location}</div>` : ''}
							${item.description ? `<div class="timeline-description" style="font-size: 0.85rem; color: #999; margin-top: 5px;">${item.description}</div>` : ''}
							${item.date ? `<div class="timeline-date">${item.date}</div>` : ''}
						</div>
					</div>
				`;
			});
			
			timelineHtml += `
					</div>
					<div style="margin-top: 20px; text-align: center;">
						<a href="#" class="view-travel-history" data-tracking-number="${trackingData.tracking_number || ''}" style="color: var(--o-color-1, #017e84); text-decoration: none; cursor: pointer;">↓ View travel history</a>
					</div>
				</div>
			`;
			
			return timelineHtml;
		},

		_onViewTravelHistory: function(ev) {
			let self = this;
			ev.preventDefault();
			
			// Get tracking number from data attribute
			let $target = self.$el.find(ev.currentTarget);
			let trackingNumber = $target.data('tracking-number');
			if (!trackingNumber) {
				// Try to get from current tracking data
				trackingNumber = self.$el.find("#trackingNumberInput").val();
			}
			
			// Ensure tracking number is a string
			trackingNumber = String(trackingNumber || '');
			
			// Set tracking ID in modal header
			self.$el.find('#travelHistoryTrackingId').text(trackingNumber || 'N/A');
			
			// Get scan events from the current tracking data
			rpc("/tracking/details/update", {
				'input_data': trackingNumber,
			}).then(function(data) {
				if (data.length > 0) {
					let trackingData = data[0];
					let travelHistoryHtml = self._buildTravelHistory(trackingData);
					
					// Update modal body with travel history
					self.$el.find('#travelHistoryModal .modal-body').html(travelHistoryHtml);
					
					// Show modal using jQuery (works with Bootstrap 4/5)
					let $modal = self.$el.find('#travelHistoryModal');
					
					// Remove aria-hidden before showing to prevent accessibility warning
					$modal.removeAttr('aria-hidden');
					
					// Show modal
					$modal.modal('show');
					
					// Ensure aria-hidden is properly managed after modal is shown
					$modal.one('shown.bs.modal', function() {
						$(this).removeAttr('aria-hidden');
					});
					
					// Add sort functionality
					self.$el.find('#travelHistorySort').off('change').on('change', function() {
						let sortOrder = self.$el.find(this).val();
						self._sortTravelHistory(sortOrder);
					});
				}
			});
		},
		
		_sortTravelHistory: function(order) {
			let self = this;
			let dateGroups = Array.from(self.$el.find('.travel-history-date-group'));
			
			// Sort date groups
			dateGroups.sort((a, b) => {
				let dateA = self.$el.find(a).find('.travel-history-date-header').text();
				let dateB = self.$el.find(b).find('.travel-history-date-header').text();
				// Simple string comparison for dates in format "Day, M/D/YY"
				if (order === 'desc') {
					return dateB.localeCompare(dateA);
				} else {
					return dateA.localeCompare(dateB);
				}
			});
			
			// Re-append in sorted order
			let container = self.$el.find('.travel-history-timeline');
			container.empty();
			dateGroups.forEach(group => {
				container.append(group);
			});
		},

		_onCloseTravelHistory: function(ev) {
			let self = this;
			ev.preventDefault();
			// Hide modal using jQuery
			let $modal = self.$el.find('#travelHistoryModal');
			$modal.modal('hide');
			
			// Ensure aria-hidden is set when modal is hidden
			$modal.one('hidden.bs.modal', function() {
				$(this).attr('aria-hidden', 'true');
			});
		},

		_buildTravelHistory: function(trackingData) {
			let self = this;
			
			// Group scan events by date
			let eventsByDate = {};
			let allEvents = [];
			
			if (trackingData.scan_events && Array.isArray(trackingData.scan_events) && trackingData.scan_events.length > 0) {
				trackingData.scan_events.forEach((event) => {
					let eventDate = event.date || '';
					let eventDesc = event.eventDescription || event.eventType || '';
					let scanLocation = event.scanLocation || {};
					let city = scanLocation.city || '';
					let state = scanLocation.stateOrProvinceCode || '';
					let location = city + (city && state ? ', ' : '') + state;
					
					// Parse date
					let dateKey = '';
					let timeStr = '';
					let fullDate = null;
					
					if (eventDate) {
						try {
							fullDate = new Date(eventDate);
							let month = fullDate.getMonth() + 1;
							let day = fullDate.getDate();
							let year = fullDate.getFullYear().toString().slice(-2);
							let hours = fullDate.getHours();
							let minutes = fullDate.getMinutes();
							let ampm = hours >= 12 ? 'PM' : 'AM';
							hours = hours % 12;
							hours = hours ? hours : 12;
							minutes = minutes < 10 ? '0' + minutes : minutes;
							
							dateKey = `${month}/${day}/${year}`;
							timeStr = `${hours}:${minutes} ${ampm}`;
							
							// Get day name
							let dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
							let dayName = dayNames[fullDate.getDay()];
							let monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
							let monthName = monthNames[fullDate.getMonth()];
							let fullDateStr = `${dayName}, ${month}/${day}/${year}`;
							
							if (!eventsByDate[dateKey]) {
								eventsByDate[dateKey] = {
									dateStr: fullDateStr,
									events: []
								};
							}
							
							eventsByDate[dateKey].events.push({
								time: timeStr,
								description: eventDesc,
								location: location || 'Location not available',
								dateObj: fullDate
							});
						} catch(e) {
							// If date parsing fails, use original
							if (!eventsByDate['Unknown']) {
								eventsByDate['Unknown'] = {
									dateStr: 'Unknown Date',
									events: []
								};
							}
							eventsByDate['Unknown'].events.push({
								time: eventDate,
								description: eventDesc,
								location: location || 'Location not available',
								dateObj: null
							});
						}
					}
				});
			}
			
			// Sort dates (newest first by default, but we'll show ascending)
			let sortedDates = Object.keys(eventsByDate).sort((a, b) => {
				let dateA = eventsByDate[a].events[0]?.dateObj;
				let dateB = eventsByDate[b].events[0]?.dateObj;
				if (dateA && dateB) {
					return dateA - dateB; // Ascending
				}
				return 0;
			});
			
			// Build HTML
			let historyHtml = `
				<div class="travel-history-content">
					<div class="travel-history-header">
						<div class="travel-history-title">Travel history</div>
						<div class="travel-history-sort">
							<select id="travelHistorySort" class="form-select form-select-sm">
								<option value="asc">Sort by: Ascending</option>
								<option value="desc">Sort by: Descending</option>
							</select>
						</div>
					</div>
					<div class="travel-history-timeline">
			`;
			
			sortedDates.forEach((dateKey) => {
				let dateGroup = eventsByDate[dateKey];
				historyHtml += `
					<div class="travel-history-date-group">
						<div class="travel-history-date-header">${dateGroup.dateStr}</div>
						<div class="travel-history-events">
				`;
				
				// Sort events by time within each date
				dateGroup.events.sort((a, b) => {
					if (a.dateObj && b.dateObj) {
						return a.dateObj - b.dateObj; // Ascending
					}
					return 0;
				});
				
				dateGroup.events.forEach((event) => {
					let isDelivered = event.description.toLowerCase().includes('delivered');
					historyHtml += `
						<div class="travel-history-event ${isDelivered ? 'delivered' : ''}">
							<div class="travel-history-time">${event.time}</div>
							<div class="travel-history-details">
								<div class="travel-history-description">${event.description}</div>
								<div class="travel-history-location">${event.location}</div>
							</div>
						</div>
					`;
				});
				
				historyHtml += `
						</div>
					</div>
				`;
			});
			
			historyHtml += `
					</div>
				</div>
			`;
			
			return historyHtml;
		},

		_onDeliveryTrackingUpdate: function(ev) {
			let self = this
			// Submit event handler for editing tracking status form
			self.$el.find('#editTrackingStatusForm').submit(function(e) {
				e.preventDefault();
				// Get input values
				var trackingNumber = self.$el.find("#trackingNumber").val();
				var apiKey = self.$el.find("#apiKey").val();
				var trackingStatus = self.$el.find("#trackingStatus").val();

				// Call the server-side controller to edit tracking status
				rpc("/tracking/details/edit", {
                    'api_key': apiKey,
					'tracking_number': trackingNumber,
					'tracking_status': trackingStatus,
                }).then(function(data) {
                    if (data.length > 0) {
						// Show success modal if data is returned
						self.$el.find('#successApiKey').modal('show');
					} else {
						// Show failure modal if no data is returned
						self.$el.find('#failedApiKey').modal('show');
					}
                });
			});
		},
})

