docker build -f Dockerfile -t k8s-resource-right-sizing .
docker rm k8s-resource-right-sizing
docker create --name k8s-resource-right-sizing k8s-resource-right-sizing
docker commit k8s-resource-right-sizing umairedu/k8s-resource-right-sizing:latest
docker push umairedu/k8s-resource-right-sizing:latest
