include .env

AYON_ADDON_VERSION=$(shell python -c "import os;import sys;content={};f=open('$(CURDIR)/../../package.py');exec(f.read(),content);f.close();print(content['version'])")
AYON_ADDON_NAME=kitsu
BASE_NAME := ayon-$(AYON_ADDON_NAME)-processor
IMAGE := ynput/$(BASE_NAME):$(AYON_ADDON_VERSION)
default:
	@echo * *************************
	@echo * Ayon Kitsu $(AYON_ADDON_VERSION) Service Builder
	@echo * Docker image name: $(IMAGE)
	@echo * *************************
	@echo * 
	@echo * Usage: make [target]
	@echo *  
	@echo * Targets:
	@echo *   run          Run service without building.
	@echo *   build        Build docker image.
	@echo *   clean        Remove local images.
	@echo *   dev          Run a service locally
	@echo *   dist         Upload the image to a registry

export AYON_ADDON_VERSION
export AYON_ADDON_NAME
export AYON_API_KEY
export AYON_SERVER_URL

run:
	poetry run python -m processor

build:
	docker build -t $(IMAGE) -f Dockerfile .

clean:
	docker rmi $(IMAGE)

clean-build: clean
	build

dist: build
	docker push $(IMAGE)

dev: build
	docker run --rm -u ayonuser -ti \
		--hostname kitsu-dev-worker \
		--env AYON_API_KEY=${AYON_API_KEY} \
		--env AYON_SERVER_URL=${AYON_SERVER_URL} \
		--env AYON_ADDON_NAME=${AYON_ADDON_NAME} \
		--env AYON_ADDON_VERSION=$(AYON_ADDON_VERSION) \
		$(IMAGE) python -m processor
