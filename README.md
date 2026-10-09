# scigantic-facebase

Search [FaceBase](https://www.facebase.org), the craniofacial research data hub, and read its open-access data from Python.

FaceBase holds about 1,070 open datasets: micro-CT and light-sheet imaging, ChIP-seq and RNA-seq tracks, expression tables and more, from mouse, zebrafish, human and other models. This package is a typed layer over FaceBase's open metadata API and file store. No key or login is needed.

```
pip install scigantic-facebase
```

## Use

```python
import scigantic_facebase as fb

hits = fb.search("zebrafish thyroid microCT")     # newest first
ds = hits[0]
print(ds.title, ds.doi_url)
print(fb.cite(ds))

files = fb.files(ds)                               # size, MD5, download URL
fb.download(files[0], "data/")                     # MD5-checked
```

Search matches every word against the whole record, and treats "zebrafish" and "Danio rerio", "mouse" and "Mus musculus" as the same thing.

## Read a micro-CT scan without downloading it

Many micro-CT datasets are a zip of TIFF slices. A zip keeps its directory at the end, so one slice costs one HTTP range request.

```python
stack = fb.microct.open_stack(files[0])
len(stack)                  # 596 slices
stack.voxel_size_um         # 10.5, from the scan log
img = stack.read_slice(300)
vol = stack.volume(step=10) # every 10th slice, (z, y, x)
stack.bytes_fetched         # a few MB of a 49 MB file
```

`fb.microct.thyroid_atlas()` lists the zebrafish thyroid-hormone atlas: 81 head scans from 12 to 25 mm standard length, raised hypothyroid, euthyroid or hyperthyroid.

`fb.open_remote(file)` gives any FaceBase file as a seekable file object backed by range requests, which `zipfile`, `tifffile` and `h5py` accept.

## What is not here

Protected human-subjects datasets sit behind FaceBase's data access request. Their metadata is public and `fb.search(include_protected=True)` lists them, but reading their files raises `FacebaseAccessError`.

## Terms of use

Copyright to FaceBase data belongs to the contributing investigators. FaceBase's [Terms of Use](https://www.facebase.org/policies/tou/) ask users to cite the dataset, acknowledge FaceBase, and send other people to FaceBase instead of circulating downloaded files. `fb.cite()` produces the citation. This package fetches from FaceBase on request and does not mirror anything.

## License

MIT-0 for this code. The data carries its own terms.
