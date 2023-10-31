VERSION=$(shell python -c "import os;import sys;content={};f=open('$(CURDIR)/../../version.py');exec(f.read(),content);f.close();print(content['__version__'])")
BASE_NAME := ayon-kitsu-processor
IMAGE := ynput/$(BASE_NAME):$(VERSION)

run:
	AYON_SERVER_URL=http://localhost:5000 AYON_ADDON_NAME=kitsu AYON_ADDON_VERSION=$(VERSION) AYON_API_KEY=veryinsecurapikey poetry run python -m processor


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
		--env AYON_API_KEY=veryinsecurapikey \
		--env AYON_SERVER_URL="http://192.168.5.141:5000" \
		--env AYON_ADDON_NAME=kitsu \
		--env AYON_ADDON_VERSION=$(VERSION) \
		$(IMAGE) python -m processor
