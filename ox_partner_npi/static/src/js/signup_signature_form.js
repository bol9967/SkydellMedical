/** @odoo-module **/

import { Component } from "@odoo/owl";
import { SignatureForm } from "@portal/signature_form/signature_form";
import { rpc } from "@web/core/network/rpc";

export class SignupSignatureForm extends SignatureForm {
    static template = "ox_partner_npi.SignupSignatureForm";
    
    async onClickSubmit() {
        // Check scroll state before submitting
        const scrolledToBottom = window.signupTermsScrolled ? window.signupTermsScrolled() : false;
        const termsId = window.getSignupTermsId ? window.getSignupTermsId() : null;
        
        if (!scrolledToBottom) {
            this.state.error = 'Please scroll to the bottom of the Terms & Conditions before accepting.';
            return;
        }
        
        const button = document.querySelector('.o_portal_sign_submit');
        const icon = button ? button.removeChild(button.firstChild) : null;
        const restoreBtnLoading = button ? addLoadingEffect(button) : null;

        const name = this.signature.name;
        const signature = this.signature.getSignatureImage().split(",")[1];
        
        // Add scroll state and terms_id to RPC params
        const params = { 
            name, 
            signature,
            scrolled_to_bottom: true,
            terms_id: termsId
        };
        
        const data = await rpc(this.props.callUrl, params);
        
        if (data.force_refresh) {
            if (restoreBtnLoading) restoreBtnLoading();
            if (icon && button) button.prepend(icon);
            if (data.redirect_url) {
                // Add a small delay to ensure session is saved on server before redirect
                // This prevents session data from being lost during the redirect
                setTimeout(function() {
                    window.location.href = data.redirect_url;
                }, 500);
            } else {
                setTimeout(function() {
                    window.location.reload();
                }, 500);
            }
            return new Promise(() => {});
        }
        
        this.state.error = data.error || false;
        this.state.success = !data.error && {
            message: data.message,
            redirectUrl: data.redirect_url,
            redirectMessage: data.redirect_message,
        };
    }
}
