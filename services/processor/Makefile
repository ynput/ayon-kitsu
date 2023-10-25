image := ynput/ayon-kitsu-processor:0.1.2

run:
	AYON_SERVER_URL=http://localhost:5000 AYON_ADDON_NAME=kitsu AYON_ADDON_VERSION=0.1.1 AYON_API_KEY=veryinsecurapikey poetry run python -m processor


build:
	docker build -t $(image)  . 

clean:
	docker rmi $(image)

dist: build
	docker push $(image)


dev: build
	docker run --rm -ti \
		-v $(CURDIR):/service \
		--hostname worker-test \
		--env AYON_API_KEY=veryinsecurapikey \
		--env AYON_SERVER_URL="http://192.168.5.141:5000" \
		--env AYON_ADDON_NAME=kitsu \
		--env AYON_ADDON_VERSION=0.1.1 \
		$(image) python -m processor
