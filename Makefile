.PHONY: test demo
PY ?= python3
test:
	$(PY) -m unittest discover -s tests -v
demo:
	$(PY) -m rpx.demo
