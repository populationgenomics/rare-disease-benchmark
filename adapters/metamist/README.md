# metamist

Adapters between the build pipeline (`build/`) and [Metamist](https://github.com/populationgenomics/metamist), for
deployments that keep their samples there. The pipeline knows no registry: it takes a sample sheet and publishes a
manifest (`samples.json`, `family.json`; see `build/README.md`). These adapters write the sheet from Metamist and
register the manifest's outputs in it.
