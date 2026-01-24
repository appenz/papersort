# Load environment variables from .env if it exists
-include .env

# Docker configuration
APPNAME = papersort
REPO ?= us-west1-docker.pkg.dev/polar-arcana-175022/anet/appenz
ARCH ?= $(shell uname -m)
TARGET_ARCH ?= x86_64

# Deployment commands
DEPLOYSCRIPT = \
	cd papersort && \
	docker pull $(REPO)/$(APPNAME):latest && \
	docker tag $(REPO)/$(APPNAME):latest $(APPNAME):latest && \
	docker stop $(APPNAME) || true && \
	docker rm $(APPNAME) || true && \
	docker run -d --name $(APPNAME) --restart=unless-stopped --env-file docker.env $(APPNAME):latest

.PHONY: run clean showlayout test dedup build build-arm64 build-x86_64 push deploy undeploy docker-env

# ---- Local Development ----

run:
	uv run main.py

run-test-inbox:
	uv run main.py --inbox local:inbox --verify --update --cli

showlayout:
	uv run main.py --showlayout

dedup:
	uv run main.py --deduplicate

test:
	uv run pytest tests/ -v

clean:
	rm -f ~/Library/Application\ Support/papersort/metadata.db

# ---- Docker ----

build: build-$(ARCH)

build-arm64:
	docker buildx build --platform linux/arm64 -t $(APPNAME):arm64 .

build-x86_64:
	docker buildx build --platform linux/amd64 -t $(APPNAME):x86_64 .

docker-clean:
	docker container prune --filter "label=myapp=$(APPNAME)"
	docker rmi $$(docker images -q $(APPNAME):$(ARCH)) 2>/dev/null || true

docker-run: build-$(ARCH)
	docker run -it --env-file docker.env --label=myapp=$(APPNAME) $(APPNAME):$(ARCH)

docker-env:
	uv run utils/gen_docker_env.py

push: build-x86_64
	docker buildx build --platform linux/x86_64 \
		-t $(REPO)/$(APPNAME):x86_64 \
		-t $(REPO)/$(APPNAME):latest \
		--push .

deploy: push
	ssh appenz@192.168.4.21 "sudo bash -i -c '$(DEPLOYSCRIPT)'"

undeploy:
	ssh appenz@192.168.4.21 "sudo bash -i -c 'docker rm -f $(APPNAME)'"
