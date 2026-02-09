# UK EO Data Hub Platform: ADES-FastApi Component

This component is the initial implementation of the User Account Service (UAS) that sits in front of the Workflow Runner service, based on the ADES, and allows more refined interaction with the workflow runner within the EO Data Hub. This repository provides a FastApi application that makes calls to the ADES component, also containing middleware which authenticates the incoming requests using an OPA client. Access to workflows and jobs is determined based on OPA responses and Workflow access policies, defined in S3.

# Development of this component

## Run the server locally
This application uses a uvicorn server to run the FastApi application, you can initiate this server locally using the below command:
```commandline
make run-local
```
This application also requires access an ADES service as well as an OPA client via URLs, which can be provided using the following environment variables:
```commandline
OPA_SERVICE_ENDPOINT
ADES_SERVICE_ENDPOINT
```

## Getting started

### Prerequisites

- Python 3.13
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

### Install via makefile

```commandline
make setup
```

This will install all dependencies using `uv sync` and set up `pre-commit` hooks.

It's safe and fast to run `make setup` repeatedly as it will only update these things if
they have changed.

After `make setup` you can run `make pre-commit` to run pre-commit checks on staged changes and
`make pre-commit-all` to run them on all files. This replicates the linter checks that
run from GitHub actions.

## Building and testing

This component uses `pytest` tests and `ruff` for linting and formatting, and `pyright` for type checking.
When testing this module, you need to ensure you have unset the environment variable `ENABLE_OPA_POLICY_CHECK`, or set it to `true`: `export ENABLE_OPA_POLICY_CHECK=true`,
so ensure the policy is checked when testing.

A number of `make` targets are defined:
* `make test`: run tests continuously (using `pytest-watcher`)
* `make testonce`: run tests once
* `make format`: format and auto-fix lint issues
* `make check`: run all linting and type checking (ruff, pyright, validate-pyproject)
* `make dockerbuild`: build a `latest` Docker image (use `make dockerbuild VERSION=1.2.3` for a release image)
* `make dockerpush`: push a `latest` Docker image (again, you can add `VERSION=1.2.3`) - normally this should be done
  only via the build system and its GitHub actions.

## Managing requirements

Dependencies are specified in `pyproject.toml`. After changing them:

* Run `uv sync` to update the lockfile and install dependencies.
* Run `make testonce` to verify tests still pass.
* Commit both `pyproject.toml` and `uv.lock`.

## Releasing

Ensure that `make check` and `make testonce` work correctly and produce no further changes to code formatting before
continuing.

Releases tagged `latest` and targeted at development environments can be created from the `main` branch. Releases for
installation in non-development environments should be created from a Git tag named using semantic versioning. For
example, using

* `git tag v1.2.3`
* `git push --tags`
