# Third-party notices

DaveBridge is MIT licensed, Copyright (c) 2026 Spencer Callicott (see `LICENSE`). It contains or is built from the following third-party work. Each notice below must be kept with copies of DaveBridge.

## GT New Horizons ExampleMod template

The build setup (Gradle buildscript, wrapper and project layout) comes from the GT New Horizons ExampleMod 1.7.10 template, by way of github.com/Tuxprogrammer/ExampleMod1.7.10.

```
MIT License

Copyright (c) 2021 Johann Bernhardt

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Java-WebSocket 1.6.0

Shaded into the jar under `com.tuxprogrammer.davebridge.shadow`. Source: https://github.com/TooTallNate/Java-WebSocket

```
 Copyright (c) 2010-2020 Nathan Rajlich

 Permission is hereby granted, free of charge, to any person
 obtaining a copy of this software and associated documentation
 files (the "Software"), to deal in the Software without
 restriction, including without limitation the rights to use,
 copy, modify, merge, publish, distribute, sublicense, and/or sell
 copies of the Software, and to permit persons to whom the
 Software is furnished to do so, subject to the following
 conditions:

 The above copyright notice and this permission notice shall be
 included in all copies or substantial portions of the Software.

 THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
 EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
 OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
 NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
 HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
 WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
 OTHER DEALINGS IN THE SOFTWARE.
```

## SLF4J API 2.0.13

Shaded into the jar under `com.tuxprogrammer.davebridge.shadow` (a dependency of Java-WebSocket). Source: https://github.com/qos-ch/slf4j

```
Copyright (c) 2004-2022 QOS.ch Sarl (Switzerland)
All rights reserved.

Permission is hereby granted, free  of charge, to any person obtaining
a  copy  of this  software  and  associated  documentation files  (the
"Software"), to  deal in  the Software without  restriction, including
without limitation  the rights to  use, copy, modify,  merge, publish,
distribute,  sublicense, and/or sell  copies of  the Software,  and to
permit persons to whom the Software  is furnished to do so, subject to
the following conditions:

The  above  copyright  notice  and  this permission  notice  shall  be
included in all copies or substantial portions of the Software.

THE  SOFTWARE IS  PROVIDED  "AS  IS", WITHOUT  WARRANTY  OF ANY  KIND,
EXPRESS OR  IMPLIED, INCLUDING  BUT NOT LIMITED  TO THE  WARRANTIES OF
MERCHANTABILITY,    FITNESS    FOR    A   PARTICULAR    PURPOSE    AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE,  ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.



```

## Assets reused from GregGuns

`assets/davebridge/textures/entity/dave.png` is GregGuns' Dictator Dave skin (`assets/gregguns/textures/entity/dictator.png`, GregGuns commit a1d6097b). It is an original procedurally generated asset (GregGuns `tools/asset-gen/models.py`, listed in GregGuns `docs/assets/CREDITS.md`), MIT licensed, Copyright (c) 2026 Spencer Callicott, the same holder as DaveBridge. It is a 64x64 standard biped skin in the old layout (top half used, lower half transparent). DaveBridge draws it on the guided-demonstration ghost (a `ModelBiped` with a 64-pixel texture height). Checked 2026-11-01: byte-identical (SHA-256 `9abcbd29ce038e99a99441c3b3010e4ceb607bcf98ea2b117e2c7cfdb1ea8556`) to `src/main/resources/assets/gregguns/textures/entity/dictator.png` at GregGuns commit a1d6097b, whose `LICENSE` at that commit is MIT, Copyright (c) 2026 Spencer Callicott, and whose `docs/assets/CREDITS.md` lists it (`model.entity.dictator`) as MIT.
