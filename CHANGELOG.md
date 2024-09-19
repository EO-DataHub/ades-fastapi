# Changelog

## v0.1.4 (2024-09-19)

Update to support public workflows
- New OPA policy management to include additional fields required to confirm access
- Splitting up code for clarity
- Removing unnecessary functions

## v0.1.1 (2024-09-04)

Bugfix
- Add link replacement logic for occurences of "localhost"
- Correct Content-Type headers when JSONDecodeErrors are raised

## v0.1.0 (2024-08-01)

Initial Commit for ades-fastapi user service
- Add FastApi application to sit in front of ADES requests
- Add middleware to integrate with OPA authentication to restrict user access

