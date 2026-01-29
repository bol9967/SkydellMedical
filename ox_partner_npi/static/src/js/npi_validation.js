/** @odoo-module **/

(function() {
    'use strict';

    document.addEventListener('DOMContentLoaded', function() {
        const npiInput = document.getElementById('npi_number');
        const feedbackDiv = document.getElementById('npi_validation_feedback');
        const messageDiv = document.getElementById('npi_validation_message');
        const signupForm = document.querySelector('form[action*="signup"]');
        
        if (!npiInput || !feedbackDiv || !messageDiv) {
            return; // Elements not found, exit
        }
        
        // Skip validation if NPI field is readonly (password set page)
        if (npiInput.hasAttribute('readonly') || npiInput.readOnly) {
            return; // Exit - no validation needed on password set page
        }

        let validationTimeout;
        let isValidNPI = false;

        // Format NPI input (only digits, max 10)
        npiInput.addEventListener('input', function(e) {
            let value = e.target.value.replace(/\D/g, ''); // Remove non-digits
            if (value.length > 10) {
                value = value.substring(0, 10);
            }
            e.target.value = value;
            
            // Reset validation state
            isValidNPI = false;
            hideFeedback();
        });

        // Validate NPI on blur or after typing stops
        npiInput.addEventListener('blur', function() {
            validateNPI();
        });

        npiInput.addEventListener('input', function() {
            clearTimeout(validationTimeout);
            hideFeedback();
            
            const value = npiInput.value.trim();
            if (value.length === 10) {
                // Wait 500ms after user stops typing
                validationTimeout = setTimeout(function() {
                    validateNPI();
                }, 500);
            } else if (value.length > 0) {
                showFeedback('NPI number must be exactly 10 digits.', 'danger');
            }
        });

        // Prevent form submission if NPI is invalid or name doesn't match
        function validateBeforeSubmit(e) {
            const npiValue = npiInput.value.trim();
            const nameInput = document.querySelector('input[name="name"], input[id="name"]');
            const signupName = nameInput ? nameInput.value.trim() : '';
            
            if (!npiValue) {
                e.preventDefault();
                e.stopPropagation();
                showFeedback('NPI number is required to complete signup.', 'danger');
                npiInput.focus();
                return false;
            }
            
            if (!signupName) {
                e.preventDefault();
                e.stopPropagation();
                highlightFieldError('name', 'Name is required to complete signup.');
                if (nameInput) nameInput.focus();
                return false;
            }
            
            if (!isValidNPI) {
                e.preventDefault();
                e.stopPropagation();
                showFeedback('Please wait for NPI validation to complete or provide a valid NPI number.', 'danger');
                npiInput.focus();
                return false;
            }
            
            // Final check - if validation hasn't completed yet, block submission
            // The async validation should have already run, but we check the flag
            if (!isValidNPI) {
                e.preventDefault();
                e.stopPropagation();
                showFeedback('Please wait for NPI validation to complete. If the error persists, please check that your name matches the NPI registry.', 'danger');
                return false;
            }
            
            return true;
        }

        if (signupForm) {
            signupForm.addEventListener('submit', validateBeforeSubmit);
        } else {
            // Try to find form by other selectors
            const forms = document.querySelectorAll('form');
            forms.forEach(function(form) {
                if (form.action && form.action.includes('signup')) {
                    form.addEventListener('submit', validateBeforeSubmit);
                }
            });
        }

        function validateNPI() {
            const npiValue = npiInput.value.trim();
            
            if (!npiValue) {
                showFeedback('NPI number is required.', 'danger');
                isValidNPI = false;
                return;
            }

            if (npiValue.length !== 10 || !/^\d+$/.test(npiValue)) {
                showFeedback('NPI number must be exactly 10 digits.', 'danger');
                isValidNPI = false;
                return;
            }

            // Get name from signup form if available
            const nameInput = document.querySelector('input[name="name"], input[id="name"]');
            const signupName = nameInput ? nameInput.value.trim() : '';
            
            // If name is required but not provided, show error
            if (!signupName) {
                showFeedback('Please enter your name to validate against NPI registry.', 'danger');
                isValidNPI = false;
                highlightFieldError('name', 'Name is required for NPI validation.');
                return;
            }

            // Show loading state
            showFeedback('Validating NPI number and name...', 'info');
            npiInput.disabled = true;

            // Call validation endpoint using Odoo JSON-RPC format
            const params = {
                npi_number: npiValue
            };
            
            // Add name if available for validation
            if (signupName) {
                params.signup_name = signupName;
            }

            fetch('/web/signup/validate_npi', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    jsonrpc: '2.0',
                    method: 'call',
                    params: params
                })
            })
            .then(response => response.json())
            .then(data => {
                npiInput.disabled = false;
                
                // Handle Odoo JSON-RPC response format
                const result = data.result || data;
                
                if (result && result.valid) {
                    showFeedback('✓ Valid NPI number.', 'success');
                    isValidNPI = true;
                    // Clear any name field errors
                    clearFieldError('name');
                } else {
                    const message = result && result.message 
                        ? result.message 
                        : 'Invalid NPI number. Please provide a valid NPI number to complete signup.';
                    showFeedback(message, 'danger');
                    isValidNPI = false;
                    
                    // Highlight the field with error
                    const errorField = result && result.error_field ? result.error_field : 'npi_number';
                    highlightFieldError(errorField, message);
                }
            })
            .catch(error => {
                npiInput.disabled = false;
                console.error('Error validating NPI:', error);
                showFeedback('Error validating NPI. Please try again or contact support.', 'danger');
                isValidNPI = false;
            });
        }

        function showFeedback(message, type) {
            messageDiv.textContent = message;
            messageDiv.className = '';
            
            if (type === 'success') {
                messageDiv.classList.add('text-success');
            } else if (type === 'danger') {
                messageDiv.classList.add('text-danger');
            } else if (type === 'info') {
                messageDiv.classList.add('text-info');
            }
            
            feedbackDiv.style.display = 'block';
        }

        function hideFeedback() {
            feedbackDiv.style.display = 'none';
            messageDiv.textContent = '';
        }

        function highlightFieldError(fieldName, message) {
            // Find the input field
            const fieldInput = document.querySelector(`input[name="${fieldName}"], input[id="${fieldName}"]`);
            if (fieldInput) {
                // Add error styling
                fieldInput.classList.add('is-invalid');
                fieldInput.style.borderColor = '#dc3545';
                
                // Add or update error message below the field
                let errorDiv = fieldInput.parentElement.querySelector('.field-error-message');
                if (!errorDiv) {
                    errorDiv = document.createElement('div');
                    errorDiv.className = 'field-error-message text-danger small mt-1';
                    fieldInput.parentElement.appendChild(errorDiv);
                }
                errorDiv.textContent = message;
                errorDiv.style.display = 'block';
            }
        }

        function clearFieldError(fieldName) {
            const fieldInput = document.querySelector(`input[name="${fieldName}"], input[id="${fieldName}"]`);
            if (fieldInput) {
                fieldInput.classList.remove('is-invalid');
                fieldInput.style.borderColor = '';
                
                // Remove error message
                const errorDiv = fieldInput.parentElement.querySelector('.field-error-message');
                if (errorDiv) {
                    errorDiv.style.display = 'none';
                    errorDiv.textContent = '';
                }
            }
        }

        // Clear name field error when name is changed
        const nameInput = document.querySelector('input[name="name"], input[id="name"]');
        if (nameInput) {
            nameInput.addEventListener('input', function() {
                clearFieldError('name');
                // Re-validate NPI if it was already validated
                if (isValidNPI && npiInput.value.trim().length === 10) {
                    isValidNPI = false;
                    validateNPI();
                }
            });
        }
    });
})();
