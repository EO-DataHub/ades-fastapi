# Changelog

## v0.1.2 (2024-09-10)

New Functionality and bugfixes
- Add endpoint to allow access to workflow logs
- Update deployment endpoint to prevent ADES bugs by introducing rate limit and additional check for previously deployed workflows
- Update ADES homepage to point to placeholder instead of Apache2 server page

## v0.1.1 (2024-09-04)

Bugfix
- Add link replacement logic for occurences of "localhost"
- Correct Content-Type headers when JSONDecodeErrors are raised

## v0.1.0 (2024-08-01)

Initial Commit for ades-fastapi user service
- Add FastApi application to sit in front of ADES requests
- Add middleware to integrate with OPA authentication to restrict user access

