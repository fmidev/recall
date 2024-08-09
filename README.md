# prevent - Precipitation event browser

Simple web application to browse precipitation events and related weather radar data.

The events are tagged for interesting features, such as hail, birds, or heavy attenuation.
Events can be filtered by tags. A radar animation is shown for each event.

## Deployment

### In development

Build the dev version of the main container:

```console
podman build -f Dockerfile.dev -t prevent:dev .
```

Run the development version:

```console
podman-compose -f compose.yml -f compose.dev.yml up
```
