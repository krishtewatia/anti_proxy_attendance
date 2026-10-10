# The AWS deployment. Every target is a thin wrapper around a Python script in
# infra/scripts, so each can also be run directly where `make` is not installed:
#
#     python infra/scripts/tf.py up
#
# Guide: docs/deployment/aws.md

PYTHON ?= python
TF := $(PYTHON) infra/scripts/tf.py
SECRETS := $(PYTHON) infra/scripts/manage_secrets.py

.PHONY: help up stop start status plan logs deploy backup github-vars destroy secrets secrets-list secrets-remove-bootstrap sweep

help:
	@echo "make up       create or update the deployment (asks before changing anything)"
	@echo "make stop     stop the instance; only its volume is billed while stopped"
	@echo "make start    start the instance again and wait for the site"
	@echo "make status   what exists and whether it is running"
	@echo "make plan     show what 'make up' would change, change nothing"
	@echo "make logs     start-up log and container list from the instance"
	@echo "make deploy   switch the running instance to the current origin/main"
	@echo "make backup   take a backup now and list the stored backups"
	@echo "make github-vars  print the repository variables the deploy pipeline needs"
	@echo "make destroy  remove everything, including the stored secrets"
	@echo "make secrets  create any missing secret in SSM Parameter Store"
	@echo "make secrets-list              names and dates of the stored secrets"
	@echo "make secrets-remove-bootstrap  delete the first-administrator secrets"
	@echo "make sweep    read-only check of every region for billable resources"
	@echo ""
	@echo "Running all the time or on demand is one setting: run_mode in"
	@echo "infra/terraform/terraform.tfvars (\"on_demand\" or \"always_on\"), then 'make up'."

up:
	$(TF) up

stop:
	$(TF) stop

start:
	$(TF) start

status:
	$(TF) status

plan:
	$(TF) plan

logs:
	$(TF) logs

destroy:
	$(TF) destroy

secrets:
	$(SECRETS) init

secrets-list:
	$(SECRETS) list

secrets-remove-bootstrap:
	$(SECRETS) remove-bootstrap

sweep:
	$(PYTHON) infra/scripts/sweep.py

deploy:
	$(TF) deploy

github-vars:
	$(TF) github-vars

backup:
	$(TF) backup
