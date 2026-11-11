# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The digests of the 80 fragments of atan, asin, acos and atan2 at 21b98aec,
the commit parcel M4C was cut from (python/tests/test_routines.py,
test_the_four_fragments_are_what_they_were_at_21b98aec).

DIGESTS_INV[routine][format] is five sha256 hex digests, one for each
attribute in softfloat.RND_MODES order (rne, rtz, rdn, rup, rmm), of
routines.Fragment's content as test_routines.py's fragment_digest() takes
it (the repr of (op, format, attribute, inputs, body, result, flag word,
words sorted by name, stage)), of the fragment mathlib.fragment makes and
routines.fragment hands out for the four, at the four formats: fp32's
included (parcel M4F2 built its asin, acos and atan2 before this commit).

A table of its own beside routine_digests.py's 220 of the eleven at
19de866c, which stay as they were: the four were not routines at 19de866c,
and that table and its test claim only that commit. MEASURED by the tree's
own routines.fragment once the four were routines (this parcel's
cft_golden/routines.py on the base 21b98aec), and again by mathlib.fragment
on `git archive 21b98aec python` alone: the same 80 digests, all distinct.
The table is a regression pin, not a specification: a parcel that changes a
fragment on purpose changes its entries with the lead's approval.
"""

DIGESTS_INV = {
    "atan": {
        "fp32": (
            "a1082b91ac33e982045b9913152046c936760a5e93b7cb415674f0977eb14ddc",
            "0ba3d8ceebf1bb2533bde4c4bc41ce9c3b8db371d8ce9f1c10d4eb0d2a3b8d22",
            "ef1926cd919db3bf5986aa1860691742b1ff21448956ed4277c4170c7350dc6b",
            "09c46498503c59c6c687ce73ced272dbf937d8dc9f855a683bfaf18eae4f66a2",
            "2e2905441af92940844865de866b695a97e7f17a377957ee9dcc1c0f1afa54fb",
        ),
        "fp64": (
            "483bf0b925e43448f01075a65e635f9c61f39c479be8b63e3e6cfdf8b5025d31",
            "6bcfc9afe9f6a3da8e67aac29fca2d7acfef30b1f685197cb8c14df0fc58c84f",
            "054f8c933ba32b65b878fd442b562431cbf7f819302d79cdf95bd0f5212988c5",
            "d31ec503491bf4d740165805e3bc5900062debe9f9c21abc06384e29a1eb0cf8",
            "d4258c927670eea67f9d088ba31099c51e3c3a65a89072d247936653b1a9618b",
        ),
        "fp128": (
            "ef7ac2b14db1a7b0343985bcd47604a46eb6e495698b647d48f77cc0461c420e",
            "57f1403dfe572a62a19d83da6b3b6f57a63ab08bedb6d10900e10b272aa90144",
            "2661e4fe9666dba864292870498fd620db0cd4fa1ed04712b26a5aadc022203a",
            "abc8a73316a74798552e51534cbedbaf9b00793ef8f64f3401704b781c043734",
            "18e85fe4f2445f38ec83db1facb86b568eeba85313c3854c94788a327d7d4752",
        ),
        "fp256": (
            "a3592492ecdf69ef0ffc2158a766e3d5ccbdbed3fc096170fb5ebf69d54d3215",
            "1fb5b1ab92bfb01228db014ca401ab9c84826ab342586de7608335b8359585f2",
            "b92113adc30739be573a5848e14800513404f244899504aaea0270a721831118",
            "2f775620efa9e172cba1f11b6bca18b6780761b4d7ad7de7a61e6fe2ebecd8ea",
            "111c8e6090732d70507946c6b22c869c11525f031c9d75331713bedc802f4a51",
        ),
    },
    "asin": {
        "fp32": (
            "c5c7863c21c85ee652fcd4fa0019d281327d65bfcf7ed45211ec8936376e3c52",
            "9197567ecd5d4034719ddbd4b2dc0eaa66e1fb07ea2738b19bfe5c2986242c7f",
            "36e256b784131fc68bbd0c6ffa71372fc74f0bdcb2e34dbc892059688fe8738e",
            "822babcad9ff419885b587ef3062842a0203a158d726db05f2da20f401bc6a64",
            "467a7bed719a90e196c8731d725626c69add320acaf98914cf2f31541ca0ae1a",
        ),
        "fp64": (
            "a27fbccc4d0761aa9d497ba0f12f97651ee626586c5a45727a4dd61deed8944e",
            "f16ef76fa69b0da3e31bcfe57be17f5ec49d33406297a88afa1aeec6e883eaee",
            "b0e4e5e9bc12909117fcfdc9faccd067d03ee0e109291004c11fec626b213223",
            "02e6ad7ab4074acd671e00e56cdb2f127e77f4d5522001fd1d642f73433fba88",
            "d58f28d6f591dd8a7a0e66dc5204f6ba88b0655cff244030dff14ea5fd9f7f82",
        ),
        "fp128": (
            "dad0ceb694f8728046c2ed0e8e8d9e92985de8d10a9c5344dec7476b9e03808c",
            "128c6f899d66a1f864931c9d54bed3e33e3487ac63378da4cd18f5d44a0dce56",
            "341a0888debc825c1d3fadb9eb20b72541f95ef8f02452c63a4c1b637b8439ee",
            "c50c6844ec10516b4d8b6ac31df8a869b061a8a1221b84f06af9e17b1b205994",
            "0fe520e8aaea9eb5311c96512cc205328fe6913f9987d7b77b64c194e981ffb3",
        ),
        "fp256": (
            "2f59b8066a6bbebc7947967c151ea9930e829986eed07b20cd903e394b222cd5",
            "fd530e1fc037159da1ac8307f066fa4e96b9d28b9aa2ac7a9f30afdf3f599abd",
            "6bbd3d100e2fde86ae77a00e6240091777f9feab65112e9d171c69d0cf28ea8c",
            "acbb15b24972d16347ffc7daf974cb1f29f39326dce4409bcab04b6083d55c1a",
            "6542d6daa86b55bfb00e90464c32526511ae5082cffc58f5a09f6a6ae20fe0af",
        ),
    },
    "acos": {
        "fp32": (
            "452a76bbfd38bf4d55515bc6d3f2c8843f5e14c7ac14fb782ffa64d63acfedaf",
            "b4030d3af3450f4cbaa2de9c7b0f830e3df5c055855b66f0ce1d909bc5cee095",
            "b3b33e82d7081f3c0d3a9962a6213b1caa7bf83211cda4d79dde16796d8637ff",
            "182ca09093ccf1d423a07a82436378a788e4e3ff44ffbb90d01b3fdc8b5fbf6a",
            "fe5ce58e543a13df5e092a3291663d2f3d293ce8a104a200c98e5b4d7b00dd1b",
        ),
        "fp64": (
            "a9a037272983c4254959f8c84c9eb7c3421551830db944b6d67164319d82dad0",
            "1d06dcb369d2706ed46129f41ef2cd538205a95ee7bdb0e5b1dc67a896e376f8",
            "7e2ba11878aa0d2cb03e11844c7961948701f90570df5b141649d0486bb0a5c3",
            "a104cb38ace3249f7ec19b0535aa4eccd7ae1b077116930c0b8d0402606de381",
            "b98f85ae1aae9bfacfdd15eeda06b94e6cabd495b9aff44b3b5a11cf6544f14c",
        ),
        "fp128": (
            "5a04b6c48e84ae2a49cf3b1594f12f5987324e3d088fe743cbbef97d77e6b5c5",
            "6956fa759d0b000c2f591fe5e85f0f92211e1b85179a79a1011ce019ae7a96dc",
            "da3709e47e5cd1e6b98e54515eadf73b8b061cd7c37c1d1a4d8e7a80bf98119f",
            "725910478a17934c980c7b1851953146d75244d4921d81f2ad3c7957a07f3309",
            "1518c416136c0e1c2db10cc928f4d45d6212bbc8056512fc8cee3863b0b227cf",
        ),
        "fp256": (
            "8ea6577fa591870e01507f22776d6141be20f811d1e0265c29ec539b89e82efb",
            "d66299ed75cd8958763a5bd0e03c4e8ef5d4df6f68485e78c478ec8bfec84078",
            "58e720d6915d590c1f1fa99b9e3f83338f1a696ee9caa8d747c9a42f1c47899b",
            "7c63bc1185947cd44304762cc2ea1844235a7fba61ed36bcc988319159377cbc",
            "cdccfdab498616913699a67148ac75ac492b60c6ba62a7ff48df72e518a0a80a",
        ),
    },
    "atan2": {
        "fp32": (
            "ed3b4460943ad3dd3abf6897782fdafc77c6da0959c387299847db90a583fc66",
            "6da353f1a01cef6de2d095910e5af0449f8232d1f1d18fed8241c46c89e26eb6",
            "245975da5d60e26c594720c3925d43ae7318f98681b912310f1d2dfd0eda868c",
            "8937103abbc87086215bcb16b7b932fbd6bf7d44dda7351881d03f683ee7208f",
            "1b7f24dce92125c918be9fccc05f7836c0a411414e9b3f205c3b237380c5f3c6",
        ),
        "fp64": (
            "3e9a25397b5fc75e8b542f79046e719d279bd0bdf826041b87965d0a15125552",
            "a21cdcd5150a17cd1f5af3340002fd6ab3bcb53cec8997eb2330352481678e40",
            "c05d56b88c70d19a0afb136811130461a68a5a1216bd14c4e7b37ec65dc23fb0",
            "51ff893af9a1fce4fd11fce399f53eab62551fa77c35c5a7305a48c4c5c1b790",
            "a09a49673470f83402b7824ce94c643538c732c65fdf32bbc8a769c040917b48",
        ),
        "fp128": (
            "8b3d63eb39fc244f22b5700cc3321f4b01fe8920ea8e4e04ff7360b8b46a7789",
            "a6d83a9c39ecd5df1309a3fed68a3752963194d90e440aa6b3b42bd32ec12d7d",
            "b325be2dfde439e54e46edabdb84bd34d949096971bed640c3d56df31fa15640",
            "97c5e54166733dc9ad9b9ea6979a47920bac1a9a6004107fe8076a0da62fa94a",
            "688e34ca3c7c7a26000654ed41772a13a9cba54f6c9fcda54bfb4320c69791a8",
        ),
        "fp256": (
            "2bd809b1f5d9e4e8fa58c714648604ebacad404d7d722791094f3947f15d348f",
            "3a5a772a25741e565ee0e3e8cc2693bc1fa40ba4f6737c411ac4c20609591df1",
            "bbca24a9d058079075dcec0de3d46355998ac8f3a5e1616311be235d6dc5cbea",
            "06884c0a1ef17726c2bcd951b597ecfaee56a0657c9ec411ecff997e063a2a39",
            "5def8e016b2cc5f471fd4d08c1b637831e354d4b3b602a657ef9e5fb2a16eeac",
        ),
    },
}
