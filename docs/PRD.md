# Formwise Agent — Product Requirements Document

## 1. Problem

Online forms repeatedly require the same personal information: identity details, addresses, education, contact information, document numbers, dates, and supporting documents. Re-entering this information is slow and error-prone.

Formwise is intended to reduce this repetition while keeping the user in control of sensitive actions.

## 2. Product Goal

Allow a user to maintain a secure personal data/document profile and request supported form-filling tasks through natural language.

Example:

`SSC ka form bhar do`

The system should prepare and execute the task only within explicit safety and permission boundaries.

## 3. Non-Goals

Formwise will not:

- invent missing personal information;
- bypass CAPTCHA or anti-bot protections;
- autonomously approve legal declarations;
- independently make payments;
- submit a form without the required user approval;
- expose private documents through public URLs;
- silently reuse credentials outside their permitted purpose.

## 4. Primary User Flow

1. Sign up / sign in.
2. Complete personal profile.
3. Add addresses and education information.
4. Upload relevant documents.
5. System validates and securely stores metadata and files.
6. User creates a form-filling task.
7. Agent identifies the target website/form.
8. Agent retrieves approved information.
9. Agent maps information to fields.
10. Low-confidence or missing fields are presented to the user.
11. Browser agent fills permitted fields.
12. Sensitive checkpoints require explicit approval.
13. User reviews the final form state.
14. User approves or cancels.
15. System records an audit trail.

## 5. Functional Areas

### Identity & Profile
- Authentication
- Personal information
- Addresses
- Education
- Profile verification state

### Document Vault
- Secure upload
- Metadata
- File validation
- Ownership isolation
- Verification status
- Download authorization
- Deletion
- Audit events

### Intelligence
- OCR
- Structured extraction
- Confidence scoring
- Source provenance
- Retrieval

### Agent
- Task planning
- Tool selection
- Policy checks
- State management
- Recovery

### Browser
- Isolated browser sessions
- Website navigation
- Form discovery
- Field interaction
- Evidence capture

### Review & Approval
- Field-level review
- Task-level approval
- Sensitive action checkpoints
- Cancellation / kill switch

### Audit
- Task events
- Data access events
- Approval events
- Browser actions
- Errors and recovery events

## 6. High-Impact Actions

The following must be treated as approval checkpoints by default:

- OTP submission
- CAPTCHA completion/interaction where permitted by the website and user
- Payment
- Legal declarations
- Final form submission
- Any action that materially changes an external account or application

The policy engine may impose stricter controls; it must never silently weaken mandatory safety controls.

## 7. Data Provenance

Every populated personal field should eventually have provenance such as:

- profile source;
- document source;
- extracted value;
- extraction confidence;
- user-confirmed value;
- timestamp/version.

## 8. Success Criteria

The product is successful when a user can securely maintain their information and complete a supported online form with substantially less manual typing while retaining clear visibility and control over sensitive actions.
