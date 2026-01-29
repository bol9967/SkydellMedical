/** @odoo-module **/

(function() {
    'use strict';

    document.addEventListener('DOMContentLoaded', function() {
        const otpInput = document.getElementById('otp_code');
        const otpForm = document.getElementById('otp_form');
        const verifyBtn = document.getElementById('verify_btn');

        if (!otpInput || !otpForm) {
            return; // Elements not found
        }

        // Auto-focus and format OTP input
        otpInput.focus();

        // Only allow numeric input
        otpInput.addEventListener('input', function(e) {
            // Remove any non-numeric characters
            this.value = this.value.replace(/[^0-9]/g, '');
            
            // Limit to 6 digits
            if (this.value.length > 6) {
                this.value = this.value.substring(0, 6);
            }
        });

        // Auto-submit when 6 digits are entered
        otpInput.addEventListener('input', function(e) {
            if (this.value.length === 6) {
                // Small delay to show the last digit
                setTimeout(function() {
                    verifyBtn.disabled = true;
                    verifyBtn.innerHTML = '<i class="fa fa-spinner fa-spin"/> Verifying...';
                    otpForm.submit();
                }, 300);
            }
        });

        // Handle paste event
        otpInput.addEventListener('paste', function(e) {
            e.preventDefault();
            const pastedText = (e.clipboardData || window.clipboardData).getData('text');
            const numericOnly = pastedText.replace(/[^0-9]/g, '').substring(0, 6);
            this.value = numericOnly;
            
            if (numericOnly.length === 6) {
                setTimeout(function() {
                    verifyBtn.disabled = true;
                    verifyBtn.innerHTML = '<i class="fa fa-spinner fa-spin"/> Verifying...';
                    otpForm.submit();
                }, 300);
            }
        });

        // Handle form submission - allow resend without OTP validation
        otpForm.addEventListener('submit', function(e) {
            const submitButton = document.activeElement || e.submitter;
            const isResend = submitButton && (submitButton.name === 'action' && submitButton.value === 'resend');
            
            // If resend button, allow submission without OTP validation
            if (isResend) {
                return true; // Allow resend to proceed
            }
            
            // For verify button, validate OTP
            const otpValue = otpInput.value.trim();
            if (otpValue.length !== 6) {
                e.preventDefault();
                alert('Please enter a 6-digit verification code.');
                otpInput.focus();
                return false;
            }
        });

        // Add visual feedback for each digit
        otpInput.addEventListener('keyup', function(e) {
            if (this.value.length === 6) {
                this.classList.add('is-valid');
            } else {
                this.classList.remove('is-valid');
            }
        });

        // Resend button cooldown timer (60 seconds)
        const resendBtn = document.getElementById('resend_btn');
        const resendText = document.getElementById('resend_text');
        let resendCooldown = 0;
        let resendTimer = null;

        function updateResendButton() {
            if (resendCooldown > 0) {
                resendBtn.disabled = true;
                resendText.textContent = `Resend Code (${resendCooldown}s)`;
                resendCooldown--;
                resendTimer = setTimeout(updateResendButton, 1000);
            } else {
                resendBtn.disabled = false;
                resendText.textContent = 'Resend Code';
                if (resendTimer) {
                    clearTimeout(resendTimer);
                    resendTimer = null;
                }
            }
        }

        // Check if there's a cooldown from server (stored in session or page)
        // Start cooldown timer if resend was just clicked
        if (resendBtn) {
            resendBtn.addEventListener('click', function() {
                // Start 60 second cooldown
                resendCooldown = 60;
                updateResendButton();
            });
        }
    });
})();
