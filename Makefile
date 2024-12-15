up:
	docker compose up --build

down:
	docker compose down -v

test:
	curl http://localhost:8080/service-a/call-service-b