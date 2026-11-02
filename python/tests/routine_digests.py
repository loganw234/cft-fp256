# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The digests of the 220 fragments of the eleven routines at 19de866c, the
commit M2's build for cftc was cut from (python/tests/test_routines.py,
test_the_fragments_are_what_they_were_at_19de866c).

DIGESTS[routine][format] is five sha256 hex digests, one for each attribute
in softfloat.RND_MODES order (rne, rtz, rdn, rup, rmm). Each digest is of
routines.Fragment's content - fragment_digest() in test_routines.py: the
repr of (op, format, attribute, inputs, body, result, flag word, words
sorted by name, stage) - of the fragment routines.fragment hands out for
division and root, and of mathlib.fragment's for the other nine, as made by
the tree at 19de866c. At that commit routines.fragment refused sin, cos and
tan (they were not routines yet), so their digests are of mathlib.fragment's
object, which routines.fragment hands out unchanged since M2's build.

MEASURED by a scratch script on `git archive 19de866c python`: 220 digests,
all distinct. The table is a regression pin, not a specification: a parcel
that changes a fragment on purpose changes its entries with the lead's
approval, as it would change test_mathlib_trig.py's counts.
"""

DIGESTS = {
    "div": {
        "fp32": (
            "d887691676a2d039d6f9a84355d99226797f1f642a70d82888853875539034b9",
            "ba22b0229e890ecdc72fbc7bab865a0156a21eea28496c72d96f3058a92dcdd5",
            "19c580f612ab75dabac127c93b419da5863023222dbccc82caaf40668cc77fc2",
            "4be234c57837e542c00b6eaacf9bfe8cb18bb9c41382f8270cd220cd93117a46",
            "88cea0a7fe30be682d179450188813237645d91e119f3a9e7543216f690cf9e7",
        ),
        "fp64": (
            "30f26042ae7ba500e3f17e5d5d11a4cea33f1e090917cc3cce711f549c6e0363",
            "9ad153e3a9fad87b36a1196cdbbf5a3d61eae704b18f2b2050aa43ee27903dc1",
            "4d648c64603441685daff7c5779dd38aeadf96b4f0d1da22ec069406bc38b0dc",
            "39ec994039d5876c9a02d6fbf524c7f80f88429355ea1a20ada382db1fbf3313",
            "df7a4f907bda53d2d111767f7b47879148cfd3358cc7eb8bb9a46862f7fc530a",
        ),
        "fp128": (
            "c3871521678120202825eff3cf64e78eb5d868b440594aaa3390452405eb8fd7",
            "6f7b2f02f8c6768565ff603dd1eb74a8346817de884498976ccbabcf6be5b9de",
            "16fbdda409d6b515901eceafc9ec816a45506bc684e5f6a444fb33528219b3e8",
            "a7d05e22fc69332513401e842668c45926b07b8b3e14006db5d96d1f1270c70d",
            "60953273eaa8e18a96884c169d54264fd879c7ca8da389d54853b1b2d867237b",
        ),
        "fp256": (
            "d2d6fbd2f8888906c9b09fb682b08562fb6b69d7a8f95093e983ce85db613eaf",
            "a549444a0079a5b335bd8a1bd4efac959d02f08bc97db5c12e191de26dda39e0",
            "15fcb81fdf8139a0efa3bf88d94df382d96fc26ddd4008fda6b60cb2df7285b8",
            "84007722e17e8103d024601160154ab32a8c358670159acb16ecae29b9a733f6",
            "7b03f4b4c6e6d927c6accb9c2c24aafddf42d40d9226b31030205a04888ccdf7",
        ),
    },
    "sqrt": {
        "fp32": (
            "2198ae18ded8bfe2f0910f87d20a8df8de5ac7adc09f8a405a02ce7eb97e86b1",
            "3f64d6f783a67b9168c9e62f441a2d8e7db53520d993c1c077bb1aa8a1df813f",
            "c19bc7684b1258adc0490c804c3fac953b2c965c1898a6cfc2ba69636d59fbf3",
            "10b90dc454f3a35d442a03768aa4693c66a7d826db0bc64a9e80f368f8e3ef0a",
            "aaed783c83ed98f268c394bfb9603c591125e266a2fc5bf897b5473d78b8c101",
        ),
        "fp64": (
            "26fdd55908d9d3d6b8b4335bb4e2d9ebb0bc68ce707fe432f334b7081240749c",
            "073e4f53c5afc2c2088246380e75a710c43d95be2d7141f611d984f06838a291",
            "66cda784911bdecbb5e4f806c6979346ae5a72e7818bfa3a6d305f37a3912e7a",
            "e7c976ca0d875f311c14670c40387e706e49776049c9c90d774b1b8a0081fa03",
            "9f2e566fde2873daae25b76172e009299a628c669a52f060b36f1213015dba53",
        ),
        "fp128": (
            "426c072625f26d79932ae135555f48a7233cbbcabb52879af7b20fc3a7eccffb",
            "1743ec30414f713066aad044b40d2650069bb53d1a0d261c565831393808d5ca",
            "24ab6455be8cf571e461a5427a3a2728cd02c06b46e32021336b06bab2cb64c8",
            "f66125cd88077a18508e545a2613d1e9439560c2d96a552c02bb1e04f6c21ee7",
            "c2be6c716a0018cc5fa49d34fc5e970940d2b099c733c94a1f051f339da4864d",
        ),
        "fp256": (
            "bc312d18c21b2effebf77f4e72635da815b5e93dfcdfda8533454aaf1fea660f",
            "0084a04e954b11a117b5fff1c210d5ba814c87a9708275efd00e94a73ee6d9d8",
            "a884c7b5223f79c1fa200d66178cc7b4901db79d8d572f7404af61c86580bb2e",
            "0d2adc667fd85e22b5759f0ad5e51809ffa8c782e5c99192b0619ba9a5283a99",
            "d387c4b85e223bf37170eb6ec9da32896ce8e693660ea7fa1a000511312795ab",
        ),
    },
    "exp": {
        "fp32": (
            "b78ff6748e26b3d73138c5d0bd101822925a76284c083ae986e16f40ca3f9d4a",
            "4f542255b3ff167cea67c6951ca8616895c8b510687e689608c9cb311fb73822",
            "af5932b7bc5fb2ed8604c4b34882c92f99301badde850ac3cba4fdd5193b27d5",
            "83bd32028a7b993458a83209e272ba8175250fbb65a34f011e8987fe1ca11423",
            "18faec5445cf15775e3eab0b8d37aa514c22624ce8f331b73b03113799ace18c",
        ),
        "fp64": (
            "7fa6cad72db9ea0ea0bb56eb56e8f719a5bee6602f90b15d6b6557cb54f85356",
            "2d2f5d629a9e1331d6c91fffef5e0ebec3d1feb4da7d8232e1facad610318705",
            "34039a11f0fb7427b45c2f6caaf7dadb1f729eaa3d9122a80338b2268c3f7ff8",
            "3f983907e3f9b9b73a231f9e0514ad9fdbf716960bda0e8d09161fb42e451e4d",
            "e746f270deb17e0b826f51f03c8be32c94f3a7d6affacedf2fc2462a6f15cf5f",
        ),
        "fp128": (
            "9c6175f23282faa690006c45742289fae1b2c18bb08a5a39e073eb68d429a4c0",
            "857ba2d47b821d3e2eb1ff2a7e861f452726b74a1a162494ea8eec9f438d75bc",
            "cc36a3880742105344bcd91645470e731e407f2673a70d001a7726f63d2caf96",
            "e9f8ca1776e40027c978827f39406582a3dace2713c4e51fda007798da3284e8",
            "0619379bebf8fab802848012c8596ef8345fae1ab157d1078ee21d0faafe7a74",
        ),
        "fp256": (
            "ad7de9f3fbeb4fd07614f2bef127b58ab648cded7be5bacd5f8877a8f120943e",
            "d5a159e8f9debf847f5b4b47586015e299bdb4ad82873a55675ce88002063e03",
            "2498989346f843075e421052b8a95e89af2e16382b37446c2cb622fa42040bc7",
            "04b854487adc41f6c87e77ec2d622ea29fe02a6fb5874ecfe35ecff1b6dfd466",
            "c58d228a614425e78f19b98ec181adfcaeab7aa3de8456c35b5add7c6322a1f9",
        ),
    },
    "expm1": {
        "fp32": (
            "08ba1809f978865978b201c4cc349cd52c2f1daf28c1a4720dca38691f41001e",
            "4ae45227b7dce2c71aaf6a4711ecc29c9e3c207311306ffb6d9b7bbb8fa2f6e9",
            "12a6e8c4503afafb8034e10da88664a533f5de0bc842abf8b3b27d27af58a383",
            "df91b587cc5c87fc26896b641aea2bc25e4356465d81b76510b342d620c77283",
            "b0d06936e16d5458aacf9491704b81601620c52f22e6ad92b0c425717a08e9b9",
        ),
        "fp64": (
            "0590a9ebfc31deb69a13ed7b61a87948392fa72155d16a2bf5e4cdfa60384be2",
            "4e5380df8940824f027863b65c042601913ce13f3b7c3291b067afd6852a8ce7",
            "866b637d51c374334292126f1afa54e69d053fc8df0be748f9945cab87cbdd1b",
            "fc86b82264fc7e9af2adb19737bf839e504cdb590c76ef846afb6d644353ae5a",
            "573dc989279aac61fab549073e6704a17689995ef15edbfd3aab3043b8ee3fe6",
        ),
        "fp128": (
            "7145b19b9146562d21d7d7f13b05e18ad7793df97feac969d5f944878c84f236",
            "9c1017072aee9cb050ec897d569b31d8776e7e7d5e604a561a95a64388390bd1",
            "29ef04bec574b814e3fc0bfdf2b731c28545bf64ea992c14ded8491aa1deec07",
            "7d16fe7cc38df676d95a962d120e84af2b803a71bdb40740e22319e4580c5f5f",
            "8773e7b36cdcfc45dee98bee3e8c80d91692a52088f4f957dc950743ff3c894d",
        ),
        "fp256": (
            "491be58ac38941321f82cb9b59cdf60e6da65580816e3d784265c41faec19daa",
            "f6960ef2cdb0a28df32abb4212cbc739ae6ad47124409aa5914d86bc235c841c",
            "2ec9ff52258e2734ce1e430ba8f166fe395a338a0f92f7d84119a9725a3b52eb",
            "7743e7603af82e30ff24b1cdbd9aac7eec57d47ef5d306b99e983751f878470c",
            "225ff3294dfedc21e60ca06f8ea697c6843b0c4b7d2a358f6ec60e2423ece09a",
        ),
    },
    "exp2": {
        "fp32": (
            "d9998211c0158ba0da794d57b33f35068f8a3f18d84291bf989cee5c8799d0f6",
            "24f7ab4f95130780c03994a80e1aa6c605d0040a0e91143f238a9acfd2402743",
            "ac4fe73f3d478cfedb5c813a40eda974616a82b3c7240d3c67d9893919789aed",
            "0e0f419420bc7b239ffc926ae9f9375444710a845881987cd4769724dc51e757",
            "93f822a9b07b69a6e4d038859bff297f5b81080f50db58253f20dd54016dedd1",
        ),
        "fp64": (
            "2285976fc08a17e85bd89258ff60e61b10f193a1f25a423163f925a4974e8f45",
            "1d0decbd8af0255b1470664ec23c058b2cb573dbe9e3c2418653952224f4f918",
            "285240fdaf7eb8213cae7130e1c66bcec38281456094c1c01d9b8c929ba3d57d",
            "0a9b1ca5d3e4bb9becb704db7995b01813ea7765fec2e5d55b9292dc120635ba",
            "27dbf8c653aa35766e5fcb133c8f8cfa7926a51c5f8fdde4be6cf5e95f839ffb",
        ),
        "fp128": (
            "441a8d8764feee4e4c5df17b2bff91180a8507b8d6947d9099b01099981ea746",
            "a86f52a5f987547cff1b88064d1290d8fe1aae1c1a5037f915287cb524dbb86a",
            "fddc03464cab79d41da0eee59c7ef833b29a4c03745f1589c479720b087e1c96",
            "8abef649ed15a714e0d999a6223886ae29810d0e0e5233006e17a8c6595ee01b",
            "e31cb6ffd171233fba21af349bb5f4f0b1ceb28fcd3e581e7812f10cdcb8b6ca",
        ),
        "fp256": (
            "760bff1be00d43a3b82dd90ee8bc44d5044630d26d88c7920abd9b4469466a9b",
            "dbdcf92061f7a56371e6fac88cf62ee3e7f001c2034594487eef43f3c6a645e6",
            "e79388c4a22d1c7f999d30f7aff09bfe521a64bec6be8f098a1d6c89b7106351",
            "a4c26cd196d5571295d78bb1df1f0f5a37ed6e30ba3636ee9020f7845c6a48fe",
            "644b6fc4b7444705c1a8cbf3eb361efe3a9a6fef0bf56dc6536148980a47080b",
        ),
    },
    "log": {
        "fp32": (
            "7db9340a8fe18334ff4de49d3474bf5b41fb4ad3fd444139911e6753b95b90d8",
            "45ef9afd5bb243c9989bd3cefee29d747de2a7aa518c5eaaa26478afba2927c0",
            "2a8749debfec4fefaec1ee383479c09c3010debec0bd82de2fb556f4173173e6",
            "3c2492874cc4a4676be6491e29eeddc7d82bf5bfd6544dac581d5982c371400a",
            "e0de78fd76437a1999a04959d525c0af29ebc8e1d34ba8892545ec059ad86015",
        ),
        "fp64": (
            "1c7ae05c67b379fae5e6ae00c6c00d0bfe22341bbfd0d02fc6f8c6cc9fb0bd67",
            "a3a18b949450e184c51fd3c10cf5cbc7476f8f8d4deec9c3dde973eac14bcd11",
            "c8a8287f0148b22f6a95456e736628e0bcaea123c052f6c904df99c1115215e6",
            "25e7f36f233de5fb7003e6471ecd89a213c7c238c9707b33c1d86e7e88a07992",
            "11693f23fcc8895fe32ac18683fd74ea3257fd03316248665b4508513f9a7caf",
        ),
        "fp128": (
            "75d4577033016e9d3aa143ccf55a00cd0fdfa93e493d54f9521f3daf2e9d5c05",
            "1f2f79247187561bb74511839cce2949ea0468f5f90911a9e219fb85ecdcbb8a",
            "b67edb3a4403df1b26df96f797854318357d1ede72e05e0b1cfa6880f810dc79",
            "a0aa0530482af29c5b3f353dd22f48c39cd97e1960d2741f873169db58a4017c",
            "70012c7b78ea39dc3600e5c17fbffc01f2b5799619f60275f465afd9a0cc82cf",
        ),
        "fp256": (
            "4111d53ba9e86dad526a047a4e5b13dff604842003d3f3f45da5f9b7824435f9",
            "9d9949bc73f304f9b85b55507e55a655217d0323ce13b926a87bf999cbab62b1",
            "5f94027a5d07aafa536a422718d83ea673d44e3be4356ee8bce5be14b8c6d624",
            "ddf7191a218ddb53b8969605b5467f32ff45973312bd395128d2022f6ed1b950",
            "d07d483f8f2f537a92ad77694dbb5d570cfb33094c5ac3c5626743daa932ffa1",
        ),
    },
    "log1p": {
        "fp32": (
            "2551571cbf84eb90673576efe9018373d0e1634a19785e69d12cd1440800e428",
            "7fbfcca6cfb391b93b498bb3d46f6f0e676a3930273b3baf4619997b6438f54f",
            "4908c288c4640c9dae8beb34461b206a80c04027ba41ef42a5dcc3977d05a996",
            "642793e07c5ec25ddcfad1dddf78c4d8a3d629659c95e580599e28c288740209",
            "8cbe88746715eb8e298c53d18b84218ff4010e6c630920389f3665b23f92f061",
        ),
        "fp64": (
            "bd2389f7d1fcc9bb2d11b15a92535894a57109af51ca94f1bf996b9e3e92a34c",
            "b5c849249e1c27686dddb3f6f529472a6088060a2829f84e59737a53f7758c47",
            "3e6367fa2fb16654bd414628d853e6873996e42f1eefd981b8ecf4145ae8a9fa",
            "021f05ababe5128a4f0304bbf715735afd5ad44e5aeecb5e60d9fec89034977a",
            "e6d5580c6488067d252643524d1838352189845030e5cfc17524e47514673d09",
        ),
        "fp128": (
            "def94cc56a2bf5273a038c391b301d626033abd43911f332573e8b30a46871bc",
            "6e743a59de28881d6f24b8c25ebade91d981ca128747afc05f0d67075497e3b5",
            "865f90249923788b7dd6d380223f93eac66e5d16f1b4220dd90ef2c22206f3f0",
            "d6e4c7b93c80c67313478507817320415ee62ffaa4ccb181d38870c270b96776",
            "ffffe37d9e2b806c129772cca280bb94ddc5c9232fa9f2e2d145da37e4f25121",
        ),
        "fp256": (
            "558b0b4776faf977dc665d5f3b29b4de8d74d151cbe50973e1975900d57480e7",
            "46db49687d987d1ede36758bfcb43cad1404adffe62724c919814d7c34fcac35",
            "8dda76e15391049e791c34b985dd086d113cd0f3aa11e30906f5c0359d7ba905",
            "7decf403898abf7b1518e1e7f14f40ed5c079cfcde5ce7f4d348706194023e02",
            "745da79a6f2a914fd8e1c5f37d41dc4ceba271fb0d88562a7668689a6ece4448",
        ),
    },
    "log2": {
        "fp32": (
            "95a120cff8fcfa7b5f71cb0a14ee32d30372367c357341926b9846dd6edbbb7c",
            "98a9e29707557dd2037c83ba7b74784370fbc5e187ea36a6a3c15a1df5383cf5",
            "42ea41b3c70c303a252cda1ea331b0952355945f1e4f841f64f63de361142e29",
            "8c6ce26eb59ae07d91db7ec15f7a29f1d3d2833aaf2593fbe9e0b60906d8ff70",
            "554ef792ce16c3d8eca26b1c8d31e92b0d918049076f40af9d1b31a0f79c9771",
        ),
        "fp64": (
            "46d80483e9a8843d6a921b6c80bafd3297f92d39b1b157b6648b7d4f0801478a",
            "d5ed636ad9b9c8c7fedde34bcd541e64111f1dae5626408924febab76807e0ce",
            "2fb74fe3ef4623da03a484e8b8131483c6b3dfa2d169adfcb2a86f150b6b2604",
            "c620b9d2ca5dfc0c9e65021cf0dc4e12427d60ad58374c411d2911f6b2cd857b",
            "0de454544c2a33dd00d5f0967fab0fb5bcad4c4e72e4d96a6e4034212e29f991",
        ),
        "fp128": (
            "d5d650d4dc9034ec8eb59ccbcb5355c99f569934e62efe082fbf95679abb87c4",
            "b807adfea8fc8afbf22f2aab78e7787c65f161e936bc1b00f531ac3839705677",
            "cebdebf32c0c3ef308685bb2ef7a476e865d00afd837cf7a20157d6322a3f4a9",
            "65c58eb8578b3c56245c4187ad893702c57221d1ba216ca2739cae2e163ca427",
            "5dfb03bfc89e124ae3ea020660f962a29dceb837de12be0795f94d65f1dfc1d8",
        ),
        "fp256": (
            "efd8ba6e4bf4cce6ea1494f544b9fe1b1e503c0fc0467b2ad3526702da706c6c",
            "129b1504202fc08f30591a3587f33ffb7df4987cd9c6aa465da52b9da06e8401",
            "2050b4331854cf822aebdd2c11af3ebc7e80b9882b898764b6567e404c277e28",
            "1134457184395b225b4280e5a86545ab10576529e21ef44bf42ed76c0fbfde24",
            "648dab20fbfe4afab6f3a2d56de8a3791d1d8e0c5a00a2c2c6fc41ca1571175f",
        ),
    },
    "sin": {
        "fp32": (
            "c867d9bbc83ef45d746c87e0c783334e6e44834da957cd21a452f2c3ff5eb9be",
            "b7330df1e3c99a2be1571a1469a42ff6a6810fb0a162cea62a1b992d1f6e6473",
            "000c6ec5df4be75bca56676b363ff63ac81aba9cfb0ce0be2961956cf240d783",
            "cca4f32e2524367e4b39708bafb3b9a24e6a12f98ae01f806cf5612cdab7d8d8",
            "9f534e872ac21d3ebcb1c02111110c5bdcd35be7ac1a476e932630d612f07b26",
        ),
        "fp64": (
            "4eef10b41ce975c197e0f4ff708ab2f901756b305eae2f65d0b45076e2cfd90c",
            "f41d4b6194e4b77bbe919076f22dbcfcdb74ed8151116eb1ac57da738620dbd1",
            "2c53e4fb83a669a3d12bbfa3a318b4ae400ed42ec61e090a1e1c192a2555b044",
            "d411d3156f54ff96f609b8857a8c6884f53fedf72667a4f50504b758deb207b2",
            "090ae24846f181d030c1b1ee5b599d86807c56af5753e16280c384b3bd528226",
        ),
        "fp128": (
            "b20f0bdaacca8b4cf84ac57ebf204e15ef0c6aa65a298a68f7f3b5c535daf388",
            "3286bc7fd73a5a2a8c7d30b276ecd1a49845a677542674ec7bc601fa0f7fd429",
            "44cdbc534cd2f9bd1045c12bafea0a31ef554e9b34887396f1eb577ce0e46764",
            "10a6150ce3b021e87ac74f06d3b208c36ce2d665928d48f4dd9304f952b9ccd8",
            "c554c40c9da8bb8a38df61296b96cbd77dee38b3287fbb27ea21dcfd6233616a",
        ),
        "fp256": (
            "7fb50920fd8313bd57c8cdb98bc18a35d5aaf3567b4480478ee8afb08fbc42cc",
            "4c90e58b264b50960d7bbb830fb0363c5962e35801cab85903a986f170e164f7",
            "a4fe8727ec9e21d2a2af0fd349e04fa5863db6abdbbbd169426b1cb429c4358d",
            "dfd83a9852909d90fbe10f704ad660b2fbf73e6ca66124d69830e692ef507356",
            "dddb1cd9917c070d182de9d75340cc1ac5b06138cb6390e4bdaf5ecfd0b5c885",
        ),
    },
    "cos": {
        "fp32": (
            "b379161c8a22e8900e5d75b1c11ee4cf8e408b14a1eb73fb4f1cdddf5bd33e27",
            "d74c0e451deee7ba27592a75d11b0016f862f036e7bb9e4d0e497fd97d4b0bed",
            "39167ef8cbcc02d37e2dce90abc539b4ad34b50d27737f480bbf0415b56fa17d",
            "7e58a515dc0342ae1a0a1203979ed2b1ae98edc676fb89477585959edda573f4",
            "fed60b50bb8baf2f3d3472e05501def13e1a5897d82342b390f346660976a0aa",
        ),
        "fp64": (
            "24ae5bb80de87367685919ea9346ee83bad12dc3c7a2782eca7493660d9fd27c",
            "4dc973ead672b1792424f14347e469c27ffb5f7949a8beafa0314ae281240a02",
            "585dedc70514a6fb6dc33f3e77dc3dbf529e0eb2b986fcbab39b1ef56ed0544b",
            "936643a09b0a7e79bca93ead26a6f12bb210c96f8848a0fa6dbe8079d5906491",
            "07ac49b02564ebe02b2cd0812d40eedeca74a67db4421d759db094da5d5ebcbe",
        ),
        "fp128": (
            "da9cab282c6a34e4f84727bd3fce99938a6b06d970073e9aa8c6ca2d7f41c73d",
            "4cc3ee94c278d899a25b618c85ab0fd473805e7fa642c2e79f9560c50aa910d6",
            "051c04d3c9dae53c84951b163fe1f40623b0b2011a72b81c370a794aee5e3423",
            "051d655095b23077b0dbd1e87bba6b2e3ac69156c6b409477436a6b59e55544f",
            "ba3917b3020fdce25dd16471343ccb5599ff73a46d44cfffcead92fd240ffc9f",
        ),
        "fp256": (
            "82126f85fcd2a875b14f26593be4935570029fb17cf53773a11be7ba173c12a7",
            "4e595f0730770347881f18661529d83410886df5e5fc5bcfa4d87009fd3c9dac",
            "04703ad42d9cb0410c227b61241997d7570e8210f37ad4a9f19ace5a45fe79f5",
            "27ca4711fa267483608870448b58c4423ee3e1414713c0231ccc7ed211e95650",
            "807dc994fdb7c9be204f35f79168b32d6bd24c33c9c9e26dcc1fc22f053c6655",
        ),
    },
    "tan": {
        "fp32": (
            "c226ab0683eb4c15f2b0f3bda95d3f9efa5a276a2ff1cbaa091b1873331f88db",
            "d8e1a3f1b0f2b3513b969534f20b93b70f1346cc6699dcf57faa88a499c2050a",
            "4280f05c41bf3711f9ce91e1af1d6f865aa6fb6658c5c6b58bcc48341a872baf",
            "2ec976d69e05213d0ca17578480e12bd0d6e5e428339bb3a6875e22f9c3a53a9",
            "7f3e7602dad9bc944c179ed6221aa17c044aee7a6e8fbb7f1c2ef650682b3c5e",
        ),
        "fp64": (
            "ed2f540d934a8985fedbd7a0e8bfe708abc87a4b8d2ed2772a08a419874cf3a4",
            "60becc5556338adc432a6508c4825eaf79296ba426f5aaa15619bda804a05c08",
            "eeaee14cd554c30780672c542deb5c20c2d39d47d95757440905336d4ea1a713",
            "fec6abebaf083e0fd6d8da0a1baa322ab6af8dede97b8e87cdab5bbb2b1e310d",
            "2d3eaadc3a65e12121bd0567286ca3cd61367a837e681933b77d98b9622f02d0",
        ),
        "fp128": (
            "e5a0e33413a4c618b62dcf698c752d055d88daa18e92fb1d64daadd190209041",
            "0a751d9b92dbe72daa77c494c15f5c0bade36389c99b470e6a9381f5a588d162",
            "46bdccb69e71d1ad3c0331545be68bebbdf514250ca393975df103053be55122",
            "837ed5beeeec234361fa2ddf6888b4a1d053cdea0239be48027d88a3261f3956",
            "fba4bd300c62f5e82f530b498d0db5aceec289f812e58923a3a18a21469877fa",
        ),
        "fp256": (
            "3384c687cdf188741f2e777a283bd64408bc3eb7d7d1720e74adadc51a4d9187",
            "5b6940593db10c5b2db225136e319fca04b72812262f72d4a04e73559f606df8",
            "f9341b81437128b409219a31ef6272de53e8ad41afff657466744deebb4dd576",
            "0b9161a7c7599255946627daa4e51ed256af961f8659c0b4a37e57be37e0bcf9",
            "93cd3dc8028037c94ed1494f295f434982605515aebc17bb9d9a4e9e3d9bcb36",
        ),
    },
}
