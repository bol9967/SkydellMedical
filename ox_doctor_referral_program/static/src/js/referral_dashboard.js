/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

// NOTE: This file is kept for future dashboard implementation
// Currently disabled in __manifest__.py (commented out in assets)
// To enable: uncomment dashboard assets in __manifest__.py

export class ReferralDashboardWidget extends Component {
    static template = "ox_doctor_referral_program.ReferralDashboardWidget";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        
        this.state = useState({
            loading: true,
            stats: {},
            timeFilter: 'total',
            dateFrom: this.getDateDaysAgo(30),
            dateTo: new Date().toISOString().split('T')[0],
        });
        
        this.charts = {};
        
        onMounted(() => {
            this.loadDashboardData();
        });
        
        onWillUnmount(() => {
            Object.values(this.charts).forEach(chart => {
                if (chart && chart.destroy) chart.destroy();
            });
        });
    }

    getDateDaysAgo(days) {
        const date = new Date();
        date.setDate(date.getDate() - days);
        return date.toISOString().split('T')[0];
    }

    async loadDashboardData() {
        this.state.loading = true;
        try {
            const stats = await this.orm.call(
                "referral.dashboard",
                "get_dashboard_stats",
                [],
                {
                    date_from: this.state.dateFrom,
                    date_to: this.state.dateTo,
                }
            );
            this.state.stats = stats || {};
            setTimeout(() => {
                this.renderCharts();
            }, 100);
        } catch (error) {
            console.error("Error loading dashboard data:", error);
            this.state.stats = {
                total_clicks: 0,
                unique_clicks: 0,
                total_signups: 0,
                conversion_rate: 0,
                total_revenue: 0,
                order_count: 0,
                average_order_value: 0,
                new_referrals: 0,
                active_referrers: 0,
                pending_fraud: 0,
                time_series: { dates: [], clicks: [], signups: [], revenue: [] },
                breakdown: { device: { labels: [], data: [] }, referral_type: { labels: [], data: [] } },
                sparklines: { clicks: [], signups: [], revenue: [], conversion: [] },
            };
        } finally {
            this.state.loading = false;
        }
    }

    async onDateChange() {
        await this.loadDashboardData();
    }

    setTimeFilter(filter) {
        this.state.timeFilter = filter;
        const today = new Date();
        let daysAgo = 30;
        
        if (filter === 'month') {
            daysAgo = 30;
        } else if (filter === 'year') {
            daysAgo = 365;
        } else {
            daysAgo = 365 * 2;
        }
        
        this.state.dateFrom = this.getDateDaysAgo(daysAgo);
        this.state.dateTo = today.toISOString().split('T')[0];
        this.loadDashboardData();
    }

    renderCharts() {
        if (!window.Chart) {
            console.warn("Chart.js not loaded, retrying...");
            setTimeout(() => this.renderCharts(), 200);
            return;
        }
        this.renderSparklines();
        this.renderBreakdownCharts();
        this.renderTimeSeriesCharts();
    }

    renderSparklines() {
        const sparklines = this.state.stats.sparklines || {};
        const sparklineConfig = {
            type: 'line',
            data: {
                labels: Array(sparklines.clicks?.length || 0).fill(''),
                datasets: [{
                    data: [],
                    borderColor: '#3498db',
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 0,
                    tension: 0.4,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { display: false },
                    y: { display: false }
                },
                elements: { point: { radius: 0 } }
            }
        };

        if (sparklines.clicks && sparklines.clicks.length > 0) {
            const ctx = document.getElementById('sparkline-clicks');
            if (ctx) {
                if (this.charts.sparklineClicks) this.charts.sparklineClicks.destroy();
                sparklineConfig.data.datasets[0].data = sparklines.clicks;
                this.charts.sparklineClicks = new Chart(ctx, sparklineConfig);
            }
        }

        if (sparklines.signups && sparklines.signups.length > 0) {
            const ctx = document.getElementById('sparkline-signups');
            if (ctx) {
                if (this.charts.sparklineSignups) this.charts.sparklineSignups.destroy();
                sparklineConfig.data.datasets[0].data = sparklines.signups;
                sparklineConfig.data.datasets[0].borderColor = '#27ae60';
                this.charts.sparklineSignups = new Chart(ctx, sparklineConfig);
            }
        }

        if (sparklines.conversion && sparklines.conversion.length > 0) {
            const ctx = document.getElementById('sparkline-conversion');
            if (ctx) {
                if (this.charts.sparklineConversion) this.charts.sparklineConversion.destroy();
                sparklineConfig.data.datasets[0].data = sparklines.conversion;
                sparklineConfig.data.datasets[0].borderColor = '#e67e22';
                this.charts.sparklineConversion = new Chart(ctx, sparklineConfig);
            }
        }

        if (sparklines.revenue && sparklines.revenue.length > 0) {
            const ctx = document.getElementById('sparkline-revenue');
            if (ctx) {
                if (this.charts.sparklineRevenue) this.charts.sparklineRevenue.destroy();
                sparklineConfig.data.datasets[0].data = sparklines.revenue;
                sparklineConfig.data.datasets[0].borderColor = '#9b59b6';
                this.charts.sparklineRevenue = new Chart(ctx, sparklineConfig);
            }
        }
    }

    renderBreakdownCharts() {
        const breakdown = this.state.stats.breakdown || {};
        
        if (breakdown.device && breakdown.device.data.length > 0) {
            const ctx = document.getElementById('chart-device');
            if (ctx) {
                if (this.charts.deviceChart) this.charts.deviceChart.destroy();
                this.charts.deviceChart = new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: breakdown.device.labels,
                        datasets: [{
                            label: 'Clicks',
                            data: breakdown.device.data,
                            backgroundColor: ['#3498db', '#2ecc71', '#e67e22'],
                        }]
                    },
                    options: {
                        indexAxis: 'y',
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: false },
                            title: { display: true, text: 'Clicks by Device' }
                        },
                        scales: {
                            x: { beginAtZero: true }
                        }
                    }
                });
            }
        }

        if (breakdown.referral_type && breakdown.referral_type.data.length > 0) {
            const ctx = document.getElementById('chart-referral-type');
            if (ctx) {
                if (this.charts.referralTypeChart) this.charts.referralTypeChart.destroy();
                this.charts.referralTypeChart = new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: breakdown.referral_type.labels,
                        datasets: [{
                            label: 'Referrals',
                            data: breakdown.referral_type.data,
                            backgroundColor: ['#3498db', '#2ecc71', '#95a5a6'],
                        }]
                    },
                    options: {
                        indexAxis: 'y',
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: false },
                            title: { display: true, text: 'Referrals by Type' }
                        },
                        scales: {
                            x: { beginAtZero: true }
                        }
                    }
                });
            }
        }
    }

    renderTimeSeriesCharts() {
        const timeSeries = this.state.stats.time_series || {};
        
        if (!timeSeries.dates || timeSeries.dates.length === 0) return;

        const ctx1 = document.getElementById('chart-sessions-device');
        if (ctx1) {
            if (this.charts.sessionsDeviceChart) this.charts.sessionsDeviceChart.destroy();
            this.charts.sessionsDeviceChart = new Chart(ctx1, {
                type: 'line',
                data: {
                    labels: timeSeries.dates,
                    datasets: [
                        {
                            label: 'Clicks',
                            data: timeSeries.clicks || [],
                            borderColor: '#3498db',
                            backgroundColor: 'rgba(52, 152, 219, 0.1)',
                            tension: 0.4,
                        },
                        {
                            label: 'Signups',
                            data: timeSeries.signups || [],
                            borderColor: '#2ecc71',
                            backgroundColor: 'rgba(46, 204, 113, 0.1)',
                            tension: 0.4,
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        title: { display: true, text: 'Clicks & Signups Over Time' },
                        legend: { position: 'top' }
                    },
                    scales: {
                        y: { beginAtZero: true }
                    }
                }
            });
        }

        const ctx2 = document.getElementById('chart-clicks');
        if (ctx2) {
            if (this.charts.clicksChart) this.charts.clicksChart.destroy();
            this.charts.clicksChart = new Chart(ctx2, {
                type: 'bar',
                data: {
                    labels: timeSeries.dates,
                    datasets: [{
                        label: 'Clicks',
                        data: timeSeries.clicks || [],
                        backgroundColor: '#3498db',
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        title: { display: true, text: 'Daily Clicks' }
                    },
                    scales: {
                        y: { beginAtZero: true }
                    }
                }
            });
        }

        const ctx3 = document.getElementById('chart-revenue');
        if (ctx3) {
            if (this.charts.revenueChart) this.charts.revenueChart.destroy();
            this.charts.revenueChart = new Chart(ctx3, {
                type: 'bar',
                data: {
                    labels: timeSeries.dates,
                    datasets: [{
                        label: 'Revenue',
                        data: timeSeries.revenue || [],
                        backgroundColor: '#27ae60',
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        title: { display: true, text: 'Daily Revenue' }
                    },
                    scales: {
                        y: { beginAtZero: true }
                    }
                }
            });
        }
    }

    formatCurrency(amount) {
        if (!amount) return '$0.00';
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD'
        }).format(amount);
    }

    formatPercentage(value) {
        if (!value) return '0.00%';
        return `${parseFloat(value).toFixed(2)}%`;
    }

    formatNumber(num) {
        if (!num) return '0';
        if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
        if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
        return num.toString();
    }

    async openClicks() {
        await this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Referral Link Clicks',
            res_model: 'referral.link.click',
            view_mode: 'graph,list,form',
            domain: [
                ['click_date', '>=', this.state.dateFrom + ' 00:00:00'],
                ['click_date', '<=', this.state.dateTo + ' 23:59:59']
            ],
        });
    }

    async openSignups() {
        await this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Signups',
            res_model: 'referral.link.click',
            view_mode: 'list,form',
            domain: [
                ['click_date', '>=', this.state.dateFrom + ' 00:00:00'],
                ['click_date', '<=', this.state.dateTo + ' 23:59:59'],
                ['converted', '=', true]
            ],
        });
    }

    async openRevenue() {
        await this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Orders from Referrals',
            res_model: 'sale.order',
            view_mode: 'list,form',
            domain: [
                ['date_order', '>=', this.state.dateFrom + ' 00:00:00'],
                ['date_order', '<=', this.state.dateTo + ' 23:59:59'],
                ['state', 'in', ['sale', 'done']]
            ],
        });
    }

    async openFraud() {
        await this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Fraud Detection',
            res_model: 'referral.fraud.detection',
            view_mode: 'list,form',
            domain: [['status', '=', 'pending']],
        });
    }
}

// Register as a field widget
registry.category("fields").add("referral_dashboard_widget", {
    component: ReferralDashboardWidget,
});
