/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";

export class ReferralSharingWidget extends Component {
    static template = "ox_doctor_referral_program.ReferralSharingWidget";
    
    setup() {
        this.referralCode = this.props.record.data.referral_code;
        this.referralLink = this.props.record.data.referral_link;
    }
    
    async shareOnPlatform(platform) {
        const shareUrl = this.getShareUrl(platform);
        const windowFeatures = 'width=600,height=400,menubar=no,toolbar=no,location=no';
        
        // Track the share
        try {
            await this.env.services.rpc("/ref/share", {
                referral_code: this.referralCode,
                platform: platform
            });
        } catch (error) {
            console.error("Error tracking share:", error);
        }
        
        // Open share window
        window.open(shareUrl, '_blank', windowFeatures);
    }
    
    getShareUrl(platform) {
        const encodedLink = encodeURIComponent(this.referralLink);
        const shareText = encodeURIComponent(`Check out this referral program: ${this.referralLink}`);
        
        const platforms = {
            'facebook': `https://www.facebook.com/sharer/sharer.php?u=${encodedLink}`,
            'twitter': `https://twitter.com/intent/tweet?url=${encodedLink}&text=${shareText}`,
            'linkedin': `https://www.linkedin.com/sharing/share-offsite/?url=${encodedLink}`,
            'whatsapp': `https://wa.me/?text=${shareText}`,
            'email': `mailto:?subject=Referral%20Program&body=${shareText}`,
        };
        
        return platforms[platform] || this.referralLink;
    }
    
    async copyToClipboard() {
        try {
            await navigator.clipboard.writeText(this.referralLink);
            // Track copy as share
            await this.env.services.rpc("/ref/share", {
                referral_code: this.referralCode,
                platform: 'copy_link'
            });
            alert('Referral link copied to clipboard!');
        } catch (error) {
            console.error("Error copying to clipboard:", error);
        }
    }
}

ReferralSharingWidget.props = {
    record: Object,
};

registry.category("fields").add("referral_sharing", ReferralSharingWidget);
