# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The digests of the 205 fragments of pow, powr, pown, rootn and compound at
f7a1ce95, the commit parcel M3C was cut from (python/tests/test_routines.py,
test_the_five_fragments_are_what_they_were_at_f7a1ce95).

DIGESTS_POW[(routine, n)][format] is five sha256 hex digests, one for each
attribute in softfloat.RND_MODES order (rne, rtz, rdn, rup, rmm), of
routines.Fragment's content as test_routines.py's fragment_digest() takes it
(the repr of (op, format, attribute, inputs, body, result, flag word, words
sorted by name, stage)), of the fragment mathlib.fragment makes and
routines.fragment hands out. n is None for pow and powr, which take no integer
operand, and the integer for the three keyed by one: pown at n = 0, 1, 3 and
-2^63, rootn at n = 1, 3 and -2^63 (rootn at 0 is refused by name), compound at
n = 0, 1, 3 and -2^63. pow and powr are held at the four formats (8 table rows of five, 40 digests: fp32
is the triple word's, parcel M3F1's), the three at fp64, fp128 and fp256
(33 table rows of five, 165 digests: they have no fp32 until parcel M3F2). 205 digests, all distinct. These
are the set host/tests/seq_check.py's pow part runs (parcel M3P).

A table of its own beside routine_digests.py (the 220 of the eleven at
19de866c) and routine_digests_inv.py (the 80 of the four at 21b98aec), which
stay as they were: the five were not routines at those commits. MEASURED at the
dispatch base twice: by mathlib.fragment on a git archive of f7a1ce95 python/cft_golden
alone, and by the tree's own routines.fragment once the five were routines
(this parcel, phase 1): the same 205 digests. The table is a regression pin,
not a specification: a parcel that changes a fragment on purpose changes its
entries with the lead's approval.
"""

DIGESTS_POW = {
    ('pow', None): {
        "fp32": (
            "4c61f5df9ae2bb731777228b473d2fd278b6dbecdb88df88d6203e4e0cda8a2b",
            "f3c9d63573995f4ae1e94648e40ed2b3e292594f2ef63bf06e667f421fbe838d",
            "4e3d9dc1d454a16dd9ae6fabf24f77b88a99f16f54f9cea8583938ec799f1813",
            "757f0372868e41341e544098331a68af76d66362b2c846730443904d96277dfc",
            "2414dec43166c2f44565c409ec85581977e41a4f524cb18f70dcd8b6daf6d11a",
        ),
        "fp64": (
            "80e97fc65a1cf37ec3e6084a7fee77518c9613ccc09ba2fd044eaf5257de80f0",
            "24c4ed186aeb889d5865cbab1622d2411a0862b8e7b827c0d4e25e30fe06b162",
            "cad2dfe0b60f81295f50152fd05834d7e69070a5943de2f5d3240b6b0dc6262b",
            "5703110fa6e7fedfefcf39421db64b0310c3347ddeb942ccda514c053f177da7",
            "e5d3c73f9e69bd4180a95b26c48fbd2c059914f145327278b2f3db95caf90b86",
        ),
        "fp128": (
            "8f2eb196df875de4ab611d70a22e3ff26aec34f78d767fc35cb96aebbb00acbe",
            "373c904b1bda9a29b66075da95fc0ee91e5c03fc23b6501e81d8827de8328139",
            "05d454872d92e9a97d6cd45d297d1b8180c1fcab6c83a63edec8e81243ea851e",
            "5e00f17efea4a5af8df0a3d46c48de955a1811a8dbb2ce2794cfa29f7ea113e8",
            "36e844f6530708e46b08c4da384722f2d7258c497ec11150be7119c9a9b6af77",
        ),
        "fp256": (
            "e397fccedd6aa6faa8e9e18517253e312cf992712b80dee1fbd5ba68c3532e8d",
            "6ab9a3f2160b8d3f02669305546c74b3835d2d4a1560948d32672e7a65f46ffb",
            "c605f6d88ab8f8a405455f6bdb3a77f0337916b2c534304df4a5b4251e0e8b91",
            "79c92e50ce166a93dbe18792fe88b117dda2eb798b57ae4550b07893a12e55a1",
            "4bfc6d11870bc664ae2820f5d78b12cf3b897cdea44a52516ca0a3f37760b97d",
        ),
    },
    ('powr', None): {
        "fp32": (
            "da383c02f54c679389b23ea569146f5dba45437dc68bedb4154585563e3d3cf6",
            "c7142e71104e40eb2eaaa099f8997ce369d56eb19723900749a4fcaa1657c907",
            "4e308c810c1a6cb96eb251ceee51454a80db4de52be46499cb1e1cd694ffd6f4",
            "a3cf87595204b5aeb3e4c6b0f0b45ea4d3788888a9649e9d428b70b8a25a91b8",
            "1da9e4a9391c01af1f735d3c1318e888fa2f06d6f302581516e275f98f85618e",
        ),
        "fp64": (
            "0500583f3360662aa38cc5ff18a83752d796568d4ea6d6d20019bf70f77756c4",
            "86dc03462d07e7bc5acb02f6285e0badac50ce2eab520644a08d50352ecb7bb8",
            "734c2d2bdbbf8d10461878254796a9c0be220e3b41c37f0febefe8130b6fb652",
            "6f374e36e9a0fa3c15bffecd117ed711f5f3b25c0b97abd5c00bfab10963e673",
            "975117001f51e207039f3ac2e0f22fbd0b4b0b6b400bab63d6811a26bf97fd04",
        ),
        "fp128": (
            "353d7c811b484812ad389ac73d520ec9ed2dd193449353997737d21fe29128b2",
            "74b13fc90acd316167a07c7b123ce8f787406bcd89b4c63f29720fcde5bad803",
            "68e3e7d8f20cc23400699631d290c03cbba6bf80c89880eae0a0de5e7e45d4a9",
            "c41b1693c81cdb6a2f0445c46619d5b0b7937fcbc61ffce4a08ddd63217bb90d",
            "ee1ea6b6c5fece44ff8cba81765d563d714ea7d25bacf3b7276cf77f19d67bfb",
        ),
        "fp256": (
            "b4788252ed10665532cf5ed435e93d0eee24b29cdc83886d5e5c978a6de18485",
            "7891bddf729001c3111d6f40f6edd2d38edfff461ef5045293ba2e40e2ec37f0",
            "3d1950332cf9cf82c8b126d57af24c5ca43e3fe5f3ea5f492594137f89a78676",
            "cd56e162565990f062884ff2358c4c74a4efcb9a987fcf999deb1a47588ac128",
            "d9dd76c647caedcabfb32352b85f418fe1fb7ee69e4126e6a62ef8041e18c574",
        ),
    },
    ('pown', 0): {
        "fp64": (
            "8b9a7963e6faff88169b9120aed98fa9c55532321644039d57b0efa5875fecf1",
            "af9bc7142078b40c6b5ae947d2c4064d1622be8f52f1edd9488c2dc6155867b7",
            "9623ff7cd52b913b283795efb712cfff44d13d67b97e7043912b766554834202",
            "33bbd389cde98c7dc40716d9f051f0941b3d2495163987116724fc17f6c8c660",
            "72e071582359bc8be9fd704b586f66b788e1d1988cfb47bf7cb0b4db8917a36d",
        ),
        "fp128": (
            "2fe635450560f6fb8beb40d0f816cc412b1f74d4a5a708e6439db25b1eb323a2",
            "6f291ff7114da43f6efb02be365ffeb3fdc063b4903565085f0f835592c8b071",
            "c568d9a83371eb6a3cd796cad962fa32e8a4a79e94fdd49a238e000f7622d70f",
            "6c5c5f1bba8883793c3c0ef1459de49c9cb9311015ff61cb454600d60f6cc451",
            "b95f0a1a95b894d482cbce501db3a97e6e705c0ca50c4768703c158f1eae8529",
        ),
        "fp256": (
            "f7c779d1bde3be512378e101a18c24f416734605e827cdb2c3f699d0b9f6c50a",
            "0187c69f7fa1411ffab6b50abce6c6df8be8d24ec7ae84f43a571c762a92c686",
            "b6987ca812cc16ea6d2f7d119a2c62a4640dc6fa43d4cad7ce5cf17af18299d6",
            "1f0ef1c6c214cd25679beaee51d8eeee9b8d00fa8fe7ac68677287ba70e160d6",
            "3aef6944d183cb6f1b4c0994c6cbd92f8d5c423f2a8f86c209b2d334c9bc1482",
        ),
    },
    ('pown', 1): {
        "fp64": (
            "98d7fae02a1146cf29cdf1c0e438146c867b6130f27a55cc75c38282689e5317",
            "83c5072e24f7f160ca992da9b11cfa57c41129a8c9e4b151a44047d2ef4f2f93",
            "b317c2a94da5c328695fbb891ba950b14b313b270a89586782b1304ad2900a93",
            "e9a39f5a3c1d3cae50d6bfedc64928aa9c67790c9b1deca30ed622d3fd8f6744",
            "427bf8110b8bce2450a1959ce1d7b78fac19cdb2b1d1c48de9a3f5d3db3ec0e7",
        ),
        "fp128": (
            "cbfb36ecd2f48cbb8ee5c203406d841ee74dfbb8a9d21456524d773be77e6577",
            "f64bd5d1611b352c5f9a0f0ab1ca058886f4df46fe0c0680695c74fb1a5293ca",
            "9ec4e7e691b50cbc06e5983c8b0306c42eecf7cd0a3a5e79e9a753e990825f01",
            "413bb0fd3af39c4d619f982ad609b709b4dcb9db9fa46c96f17af4767a1ebbee",
            "f87fa2d577152c777c9f8a9b00de59b9a2cebac8f09118d162fdc42fc86dcbbd",
        ),
        "fp256": (
            "c07e711501da09162004899a9f508a1e3c8ca07b80c947c131dbb13dfe4d92d6",
            "5839023f1682f4b658f40a04985eb5d9b7fec4062aa9d19b629f31b330ec02ba",
            "cc354708ba84eba37308203379f32f637d851d3fec80b2dd8e5c0f1b231e9ab2",
            "0f852601055839dc28082dfdaa7a87f2d6850c3602cb752254cd51f06612f129",
            "443bba38bcbc5260314de63cdc7246d0fbbc9ce99f533e3103a713ca94e69a9f",
        ),
    },
    ('pown', 3): {
        "fp64": (
            "6a0e2c894e36d24d9accb35eee23f9726e1f6adc3e46223955eb0b6267473022",
            "3e94a88af6bd68359113910aa363d6e0b49e7fadec601747d810ecdd4e8fc6ae",
            "12e4e2e97af8b15f437b20730069c65d3f3ea69c14cf875df861c788753021a7",
            "1b8710190f55b0217ba5c58c1d535987a297ed91d4b704abf33f2c22f089613c",
            "6223160aa83238a29416f91c3b177e5673faf9a180c40f78eaa3f79e13b47e8f",
        ),
        "fp128": (
            "34295edbe71eb29fac28198a5764d9403d23119206054469000a7de98eae6394",
            "d965409487307d72837745792f02482e680235dae3926782dadf9b2244f8cbe9",
            "bce6572e6ddd8ebc4e85b4bc11c541f435279708675abd1c9d814c1f0950fb2d",
            "9e8e8834509032b72e19a6b8c8146865807f4a63ae41f376486150db22616f77",
            "c15e0782120920180f530811281eaaf94b43bb987297879b83cd63a6a68455d1",
        ),
        "fp256": (
            "52bf001afda7fa3eccb6181695b97fe487975cc9c6d42fae586860650540849c",
            "d153a048624ec35cc77557d793e8a9f53953a19f75676c0582f373cd9cbf761d",
            "68a02517c9d0fe17eee7b55c348cadff5e0635e91a6a36bc4ddbfa370203778c",
            "fc9b79f099ca1c35e7d1884f5e6951472f48721c77856ac0909909db49cfba7d",
            "0acc0a06b6fbe5a4472ac1707f9e91d211f071c49c2e06957b373e4d02ebde45",
        ),
    },
    ('pown', -9223372036854775808): {
        "fp64": (
            "7193d6d1ad850d60d0582e682f62785136088a33e2276c719ded4dfbf96c1d34",
            "737efd59ecb1b7e578d40d7bd0258ab2359a7ba4448569def2dc4162d2770149",
            "1455d3e940e065b310289bdf93deb219243c1a2af3a82a0558e650157f691726",
            "baf2854914e18d4c9b6bae8f22e8dbe1f8651100d9e9999604a4867a5deaa743",
            "c5e643b9a3baaf80056a19ae840f7676816e03eade3207d24ec331187d6320ed",
        ),
        "fp128": (
            "b1cc7dd5d520d6e4e9817d64ff3d0f6cf7503ea70b7058eef805948d34e10d8e",
            "3a3927d640cd463087acfbe1b2e47651ed91d599d2f923d8081641ef1ecbaf22",
            "72299814ceb8a768c9908c4e7dc5665ce8a9711053ec44c6bed412512af09e89",
            "14e6e4765e7fe641cc80d0ef92b07e7119c000afb500cbed252bea0585742f89",
            "124e416fe4a2a55e466afd045b1a006ab029edcc69539418846368ab4413ec96",
        ),
        "fp256": (
            "bda46d4b2966e85061d76d7f8f2826678fc07b76b41556ac609612982c7c7d3a",
            "df1a99d6bcab626f1ccd3c7b3d4bb9a7246d9ff726819ff8985ec5ff94a8901e",
            "12beb94ead06b6113b59706b609e0eff0fe1e46347c66f043b65bd4ebbef9178",
            "c36f6311ad0ba2acd84f68d96e50dfa09dd4cb1f9e8725d30dc82595c2f0e28f",
            "3cc7760dfb5629db11c0f2b6ed5a7b0d126b0e692515ecc707576ce1a61931dd",
        ),
    },
    ('rootn', 1): {
        "fp64": (
            "8171402162ea6debe1a3adf598fed1f3fb8f374b4458d053dcd4d4df0d6eb61a",
            "ed2aa404e85f794651f9f4a7f978c1ada110b57b603f0002b30e26f14e79b2e8",
            "fcf5f9cd4a4c104c64aadbd2074fc79c11c843be9e7a4294884dba1c1f829b0a",
            "a276672a5e3b4536bb7e8ab3a1a551a4e266b4db3ce9e6dd9666e4c3062485b3",
            "155d73e60fefa5e0c74e903c77ce229b1db1862bc8503fb93e2022c80868c143",
        ),
        "fp128": (
            "da17539c012945553eeb24433eef703eed3e3743f640abaf59502fbdd55219ed",
            "02a67876d93081a07db7df45c3c2e59fface00f26945b6bc1e1557a6855b5ca6",
            "ea23eac0dfb86d8c42c1b02d7bcad0eec7fcab191eb9c4645ad596afd1d5a39e",
            "672cf7b422334e332c4123ec551b04f6c92570fdba444cb6e27129d660b95918",
            "3e533e257d684225d33c2f553a32df2741e982cc54129292d3bce83b8a7d81bb",
        ),
        "fp256": (
            "80ea35b6db917926d5881e86bd46ffab5f373ddb1055e1687ffb0564723f7956",
            "43e3dc983b67275f8471afd89e68f73c0904ec7c47898b0c21450f46f9648891",
            "815f5aa1daa58c09713017694eb15b2cd044e45597f0797df3ef0ed7bf20f960",
            "dbd724120a4f81b9e8d81c15982d3af566777fb41ea1c4e7097ff2c1647e749f",
            "512b0342d265676a5279dbb1eb2145af3fc5cb82ab15be941c48cf1c03ce3954",
        ),
    },
    ('rootn', 3): {
        "fp64": (
            "112f0a3f47ceeac77f14d8cbc6cb44466caf28171bbdc888baff20c245f2dce4",
            "477c2ab511b9d313a693b914e176fe6e6e36b0cd4bfc14ec98efc9fbd48d96f7",
            "b6514e45eb63d07d10430407c3d2a76244be806b5020047b3ef9c70e3a333cad",
            "ea06f5f44db94b7ea2182ba908e7af87ab236b2cd063499605f405d74a1e191d",
            "5680b11a4dfe012d0c87de9f96920c6e78fe84607bd746b6ea13135a0ccd05c3",
        ),
        "fp128": (
            "d2ab53fda3a657467fdc9b404f145639f3a4a660e930bf7c59b1da76f2ede69b",
            "9c27a8add7a6df454da01628eab6e305b372e0273b0cf2ef57e01a56d045c8ea",
            "8ea6aa3134d19b5b08c08f48b5b68d78cb5361a19e87d5151af036acef32cfe9",
            "43029e3e6a8dbe537d65c938cae04392c1bab431aee2913f25d2636676a460c8",
            "6e4d41eb82bb21356d1054bb5b14687e19050de14b9c34de7c41f64d0b554c47",
        ),
        "fp256": (
            "67117109a1e1241610faf112e6b6cae1b6c6f844861e99143b485c813a734355",
            "0f5a560298a4f16573d299ed182c847b1bdad15b95006258e912cd1e8ab92cc4",
            "963027aea1c23e14b84406bbb64593cf48cfc345be92b37ddc368276e78a24db",
            "107520b4de7227d216f27e76f4c535853233ec7e98de38f5f87c2885b56f97f6",
            "2eb533beaec9613f9e2eaf905521eab6648db793d76681966a93e9cdbaeb3b5a",
        ),
    },
    ('rootn', -9223372036854775808): {
        "fp64": (
            "5a8be8af5698413ed5286dea1a8596a3aa4c5c0edfbe7e9748236cf22047030d",
            "397f31fb9b611e0a996b74396e6e75582c2806c446f4db65299225166fb28e43",
            "59c5a76144ff7ea21a11040ea6eab283a70c467028ab925fec67baec2d7b1857",
            "681d1823b3bd6f63d75a15e4f5e916fe543e9a2cc344f852dfea6303f1739a13",
            "c6fd9f1bc21fbc99edbe71f2c441f98d0b68e851fee4d50764de0b87ae48560d",
        ),
        "fp128": (
            "2cfb8d7c857ae0c76780a69e17913a4c24ecd957093b6abc050c8cba4501db6a",
            "945e8322f0373d4e4f178eda42db39be997e37947886e82ad51e05c358c40895",
            "331d89eff1a522b9505b770d5e0747e0b3e65ce4ae6ded1b7958156ee5c59c83",
            "4d39e5bbe3b1d0c25463df9c1cd81e30fb46de42170bd6a395d999dfa5a04412",
            "faa6c208e33b1bd843db3200672f372936e9b4179839969f5edf9a213a4f954f",
        ),
        "fp256": (
            "092fa631df32da1ae7e997577084edc056e17974db89f1ad25b0e20a1a793290",
            "667bf3ac78c52cd44903c9d6db18d5f8d8f6a3a206ed4a3a4259fc0571dd05f3",
            "932c8ed021ffc8d653f93f5d309303277621bf050d2a0ea4693cf30a73842598",
            "32e134e2b1f912894390cca9cbf00ad79525d12c94e8e57ba07e7854f5de924b",
            "4f412436c09fb3db7fa7f013066ce0cb45fb93495b6012c39a7b0d18814d84a9",
        ),
    },
    ('compound', 0): {
        "fp64": (
            "30e6a49ff9bed09e2e430afbdcf7fbbb4905de319cd021fe528c9acb020dcd6a",
            "e80866d1bee35a05c8833bfa267814a309029bbcbd4dd0c9c6613da765ca78cb",
            "7a96325feeda93ff9323e1debeb37c7f2eb8afaf92e62516db6753312635b919",
            "0322fe617fc826d70d1845c0d3c35b6bb0df3a0664f3e9416a5d16570ad8c503",
            "5f16cfaf784309db9256cda04381ab0adf9f805ed9732b470d3851ef2668725b",
        ),
        "fp128": (
            "4c08d54d600c13b593a04942e51b8790672e72dc9bd472cdba651fecbce9a1be",
            "6b39f27444e4a388f2bf070f0aeadc5781570c986138ed753f07008239097cf3",
            "1e78c3663c9db881f75337a9e3bfb52dc95eace2db78f5ee32d1ac8268fefeb2",
            "f2a122f0114e59ddd65bcc687106a69e9c409ee7cb7310e72d34169c2d2be335",
            "c3c34867a9f8d3454cb552d2894093d10976fe36f707b51429404f87dbf39f0e",
        ),
        "fp256": (
            "6d3d999e639bc29226d31a6f0e151cb5bfa7cc9266e70c68bea9f59fbfe79a00",
            "2f86b8dc51abeecf0b884d90b219669230c072f88d92ae1d4e554c0e2f3dd87b",
            "f85ac16055e91bd74add01a6df14d89c1784645a663cdc2a90f2b1ed55e7d9c5",
            "f8eaa8888665e47210c0f4da91c754d727d2967181c815cc6cf8340909366b75",
            "5e45f7261ecff404cdd2554d51a00ccd1f5223431e999aa414c08e2a667fe3df",
        ),
    },
    ('compound', 1): {
        "fp64": (
            "568a028491b6915fb5797f759785dc37f26472e24f8858d23f2c31e2dcafb50b",
            "f1622ba38708c828640fb0d694850ca98fc783ae2952dbacafd74cf555da38d2",
            "06c566b5991ac68708955286b7cd5aa3e7fea596c128b3e6323909c05800e927",
            "23f92332cfeec5e1eb5d89af50bc04dc3804554d69ed3bb6d697ead6f9f64805",
            "3927819036d15b5a6fd57b237e733e3780cdf932405a8e385d8597a752122691",
        ),
        "fp128": (
            "6888a917c73994ecdc84df9173cc95785d4a15d03f77dd9db5179d60d8f73498",
            "176a5feda64a3a0b4858fa9b91f093f1758ddfee8f283a9398212c6b748d0456",
            "9a5d36cb05a5a8a8f1c0d9603ac6027cf795bfca758758b1c00211f1e20b86fa",
            "638bcb2bdc3ef5ce526c2f2fb518b0b8abd32f3de8ff9908b53776dc6389c3f5",
            "c50e52657538a73c304f68973dc8191a2cb813269cb03dce3ff9584d822164ae",
        ),
        "fp256": (
            "ecee3ed818eaa5d9e4f1247eab5d174b995252a5037f4d0c66f7f6b97f155210",
            "34dbbc5a23f16ceec530ce87fee6cc8a11a9fbf9540d1aab559f60ce6f1d7bc8",
            "f805080af290384d6b10184c1e7ef90cc9a126247eaaa679107f8427ff708d32",
            "31365487704eea64f2e321e4ffcd7c49490c510693d6079ef7f5c8686ffcd69b",
            "09ad16f4e1e78390345c40f31824ae4c522bad4926b25c092abf971219e32aa0",
        ),
    },
    ('compound', 3): {
        "fp64": (
            "1e86d328a061060aaaecc5f4bc5ecbf4107b077269d9774a8d380fbc9bcb3cbc",
            "7216fa67d5e3ac0f336ef0114b8b73e138b52fd18e7f783667526cb5a87b4e0d",
            "093ee2d6d9e2d4f40c10f2437f198cefe8bfc44336b234c367fdb86fdc9700f4",
            "9158c9d38144f655df67acfbde2806862d06d6ddff8d1d7a594cf3641d0d22e2",
            "485448dea759532e09bd3083e886a68701bb78c4deec96531b0a0f33078dbcbc",
        ),
        "fp128": (
            "73b3cc2708fd19235c86bc00d95f4dc98e1f4f8ac5050cc57c070491c69aff3d",
            "e69a3b2d084842900583404f67a47feb9be6cd7e342ca35354ba5b0c70d6459c",
            "b6ff9731d76ba922f0270e5f6955431ff79b1ccd85f954c872c7b7a7fb3efe6a",
            "af4ce2927536ce4c374c0eaf4f6511761b51e69e819f54dcdd3425bff87be35f",
            "a4b6f64c520fe8c9e59fa39492a98f29659d4746b69e085c52ddc6d7afbe6f00",
        ),
        "fp256": (
            "abe3ccafc3b7c45352bc4d31653933ed46a422f1d72fa8cb8ef08f3c44260893",
            "ae400e398c4dd263722b7104de6ba1980bd07fbfa55df09459e16ca73256e5c6",
            "15a022a23cb7276a618930eaff091a331f807b8a1e0e3a69e7768a58eef616c7",
            "c83a91fb7d0922142b3c5b6dd21284733d6233e5fa97039cb1b56882e9b01292",
            "a4dc72d5c898c0a943bfc8db3c960e3c12f5c4591a78ae1cf54ebc5f38f87cc8",
        ),
    },
    ('compound', -9223372036854775808): {
        "fp64": (
            "f723b546967098d1108e650ba0bf373ca506c98885a6f31004e9fa12d42c4a21",
            "d0a9c61b0ae6e808145b96da5f409465e168cf98f7fd181893fd7341288e162a",
            "e4120f570dd8accb3e49171a25d6e527307a64c373071aa74c1372b38b80acc0",
            "e86490fb2ecbfec4822680b375a60653e03583974665548bea3bd9e08826f2bd",
            "2b856d71d7c71f156fc9e381d3a6ae8e72c9f886934f502951b1f12850d6c6ba",
        ),
        "fp128": (
            "53048aaccc3c858ded4067feb50aa10537926ed0f671fa23469136e9e48026a5",
            "bd0eccecd8792e24322c060e894d569c3869bd1b5423a00bfb065f66312436d4",
            "57a400c41d7835f5c5aa850e7b254b996e1413a385fff11425bebd63d3c22936",
            "d7341ecab8e1585bd45e4cf558bdc420708e71416ba1010421fb47b0bc557e7b",
            "6e39ef52eefaa0bf8dca5f8ceb754ca3e1d3e6e5a8b60800783d81d1de293778",
        ),
        "fp256": (
            "b16f5cabae9154c7e4c294e679f634477f52cd61bda6aaf04d70f26562f0381e",
            "43542161d6f77cd4eef91df4143a8d00cdfd4bf8be557da798aa01019f4b829a",
            "27371022f87066fd7f97d51216bc145fa7f61daf288897890b6103bf1b0738c5",
            "fc1b9afe030c690b8d2e719f71020ef3a6d5c9536928264892662d54aae18958",
            "c65090a3687ba741850e975f22ff881a868ac55d3a4e7c22a22953f09f43891b",
        ),
    },
}
