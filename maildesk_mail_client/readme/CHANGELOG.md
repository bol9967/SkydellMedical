Changelog
=========

Version 19.0.1.0.0 – Initial Release
------------------------------------
- Gmail, Outlook, IMAP support
- Full OWL interface
- HTML email composer with draft and attachments
- Email threading and filtering

Version 19.0.1.0.1 – Bug fix for avatar display and date formatting in emails  
Version 19.0.1.0.2 – Optimized and accelerated IMAP synchronization processes  
Version 19.0.1.0.3 – Introduced automatic folder discovery and synchronization  
Version 19.0.1.0.4 – Improved logic for recording To, Cc, Bcc, and Reply-To  
Version 19.0.1.0.5 – Enhanced synchronization and server-side move logic; prevented duplicate message creation  
Version 19.0.1.0.6 – Improved synchronization with Gmail/Outlook servers and enhanced rendering of outgoing emails  
Version 19.0.1.0.7 – Improved synchronization and new message notifications  
Version 19.0.1.0.8 – Optimized partner email statistics (added email_count_live, SQL-based counting, improved performance and live recalculation)  
Version 19.0.1.0.9 – Improved HTML handling and inline image processing  
Version 19.0.1.1.0 – Added Sender Name field to customize and display the sender’s name in outgoing emails  
Version 19.0.1.1.1 – Fixed composer initialization errors, improved stability, and added editable attachments (rename, replace, delete)  
Version 19.0.1.1.2 – Refactored outgoing email logic with proper normalization and handling of To, Cc, and Bcc recipients to prevent duplicates and ensure correct Bcc header delivery  

Version 19.0.1.1.3 – Fixed signature editor, notification loop, and email normalization issues  
- Fixed HTML signature editor window not loading fully  
- Resolved OdooBot notification loop caused by internal email notifications  
- Added protection against duplicate notifications and improved context handling (skip_existing, resend_existing)  
- Normalized uppercase email addresses for consistent delivery  
- Updated access rights for Maildesk users to allow creating activities and mentions  

Version 19.0.2.0.0 – Major Synchronization Engine Rewrite (MailDesk 2.0 Core)
Version 19.0.2.0.1 – Improved email notification logic
Version 19.0.2.0.2 – Added safe migration layer to upgrade databases from MailDesk 1.x to MailDesk 2.0
Version 19.0.2.0.3 – Change access rules
Version 19.0.2.0.4 – Fixed Outlook account connection and synchronization via Microsoft Graph, removed IMAP dependency, and improved token handling
Version 19.0.2.0.5 – Improved folder navigation logic and fixed issue with incorrect folder selection in Outlook accounts
Version 19.0.2.0.6 – Optimized unread counter logic, fixed real-time read-status updates, and improved message selection, navigation, and folder handling