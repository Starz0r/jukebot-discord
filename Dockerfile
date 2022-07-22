FROM python:3.9.5-alpine3.13

RUN apk update && apk upgrade && apk add ca-certificates opus

RUN apk add ffmpeg --repository=http://dl-cdn.alpinelinux.org/alpine/edge/community

RUN apk add --virtual build-essentials build-base alpine-sdk libffi-dev

RUN mkdir /app/
ADD . /app/
WORKDIR /app

RUN pip install pipenv
RUN pipenv install --system --deploy

RUN apk del build-essentials

ENTRYPOINT [ "python", "./src/main.py" ]
CMD []
