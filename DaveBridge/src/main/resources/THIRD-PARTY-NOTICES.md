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

## Apache Groovy 4.0.33

Shaded into the jar under `com.tuxprogrammer.davebridge.shadow` for live eval (the core `groovy` module only). It
bundles relocated copies of ASM (BSD-3-Clause) and ANTLR 4 runtime (BSD-3-Clause), whose licenses ship in the jar
under `META-INF/licenses/`. Groovy's own `META-INF/LICENSE` and `META-INF/NOTICE` are kept in the jar.
Source: https://github.com/apache/groovy (tag GROOVY_4_0_33)

```
Apache Groovy
Copyright 2003-2025 The Apache Software Foundation

This product includes software developed at
The Apache Software Foundation (http://www.apache.org/).

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

## MCP names (Mod Coder Pack mappings, stable_12 for 1.7.10)

`assets/davebridge/eval/srg-names.tsv` pairs each SRG member name with its MCP name so eval scripts can use MCP
names at runtime. It is generated at build time from the MCP mappings the build already downloads (not committed to
this repository). The MCP mappings are the work of the MCP team and contributors; they are used here only to
translate names for modding, as the Forge toolchain itself does.

## Assets reused from GregGuns

`assets/davebridge/textures/entity/dave.png` is GregGuns' Dictator Dave skin (`assets/gregguns/textures/entity/dictator.png`, GregGuns commit a1d6097b). It is an original procedurally generated asset (GregGuns `tools/asset-gen/models.py`, listed in GregGuns `docs/assets/CREDITS.md`), MIT licensed, Copyright (c) 2026 Spencer Callicott, the same holder as DaveBridge. It is a 64x64 standard biped skin in the old layout (top half used, lower half transparent).
