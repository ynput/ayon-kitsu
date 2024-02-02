include .env

AYON_ADDON_VERSION=$(shell python -c "import os;import sys;content={};f=open('$(CURDIR)/../version.py');exec(f.read(),content);f.close();print(content['__version__'])")
AYON_ADDON_NAME=kitsu
BASE_NAME := ayon-$(AYON_ADDON_NAME)-$(SERVICE)
IMAGE := ynput/$(BASE_NAME):$(AYON_ADDON_VERSION)
SERVICE = $(error Please specify the service to build with 'SERVICE', for example: 'make build SERVICE=processor')

default:
	@echo * *************************
	@echo * Ayon Kitsu $(AYON_ADDON_VERSION) Service Builder
	@echo * Docker image name: $(IMAGE)
	@echo * *************************
	@echo * 
	@echo * Usage: make SERVICE=[service-name] [target]
	@echo *  
	@echo * Passing SERVICE is required for any of the targets to work, possible services:
	@echo *  
	@echo *   processor - Syncs a kitsu project to Ayon
	@echo *   sync-service - Listen for events on Kitsu and sync it to Ayon
	@echo *  
	@echo * Targets:
	@echo *   run          Run service without building.
	@echo *   build        Build docker image.
	@echo *   build-all    Build docker image for 'procesor' and 'sync-service'.
	@echo *   clean        Remove local images.
	@echo *   clean-build  Remove local images and build without docker cache.
	@echo *   dev          Run a service locally
	@echo *   dist         Upload the image to a registry

export AYON_ADDON_VERSION
export AYON_ADDON_NAME
export AYON_API_KEY
export AYON_SERVER_URL

run:
	poetry run python -m $(SERVICE).$(SERVICE)

build:
	docker build -t $(IMAGE) -f $(SERVICE)/Dockerfile .

build-all:
	$(foreach service,processor sync-service, docker build -t ynput/ayon-kitsu-$(service):$(ADDON_VERSION) -f $(service)/Dockerfile . &)

clean:
	docker rmi $(IMAGE)

clean-build:
	clean
	build

clean-build-all:
	$(foreach service,processor sync-service, docker build --no-cache -t ynput/ayon-kitsu-$(service):$(ADDON_VERSION) -f $(service)/Dockerfile . &)

dist:
	build
	docker push $(IMAGE)

dev:
	build
	docker run --rm -u ayonuser -ti \
		--hostname kitsu-dev-worker \
		--env AYON_API_KEY=${AYON_API_KEY} \
		--env AYON_SERVER_URL=${AYON_SERVER_URL} \
		--env AYON_ADDON_NAME=${AYON_ADDON_NAME} \
		--env AYON_ADDON_VERSION=$(AYON_ADDON_VERSION) \
		$(IMAGE) python -m $(SERVICE)
