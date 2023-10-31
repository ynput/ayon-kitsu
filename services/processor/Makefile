include .env

VERSION=$(shell python -c "import os;import sys;content={};f=open('$(CURDIR)/../../version.py');exec(f.read(),content);f.close();print(content['__version__'])")
BASE_NAME := ayon-kitsu-processor
IMAGE := ynput/$(BASE_NAME):$(VERSION)

run:
	AYON_ADDON_NAME=kitsu AYON_ADDON_VERSION=$(VERSION) poetry run python -m processor

build:
	docker build -t $(IMAGE)  .

clean:
	docker rmi $(IMAGE)

dist: build
	docker push $(IMAGE)

dev: build
	docker run --rm -ti \
		-v $(CURDIR):/service \
		--hostname worker-test \
		--env AYON_API_KEY=${AYON_API_KEY} \
		--env AYON_SERVER_URL=${AYON_SERVER_URL} \
		--env AYON_ADDON_NAME=kitsu \
		--env AYON_ADDON_VERSION=$(VERSION) \
		$(IMAGE) python -m processor
