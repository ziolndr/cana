const IMAGE_REFERENCES=[
  {name:'Blue Dream',image:'assets/featured/blue-dream.jpg',source:'Nickel Bag of Funk',license:'CC BY 2.0',source_url:'https://commons.wikimedia.org/wiki/File:Blue_Dream_(cannabis).jpg'},
  {name:'Sour Diesel',image:'assets/featured/sour-diesel.jpg',source:'Alapoet',license:'CC BY 3.0',source_url:'https://commons.wikimedia.org/wiki/File:Cannabis_(Sour_Diesel)_Flower.jpg'},
  {name:'White Rhino',image:'assets/featured/white-rhino.jpg',source:'CannabisQ',license:'CC BY 3.0',source_url:'https://commons.wikimedia.org/wiki/File:White_Rhino_Dub_Macro.JPG'},
  {name:'Acapulco Gold',image:'assets/featured/acapulco-gold.jpg',source:'KindHorta',license:'CC0 1.0',source_url:'https://commons.wikimedia.org/wiki/File:Acapulco_Gold_Female_Plant_in_Bloom_1.jpg'},
  {name:'Blueberry',image:'assets/featured/blueberry.jpg',source:'Yuri Che',license:'CC BY-SA 3.0',source_url:'https://commons.wikimedia.org/wiki/File:Blueberry_(Dutch_Passion)_01.jpg'},
  {name:'G13',aliases:['G-13','G 13'],image:'assets/featured/g13.jpg',source:'Sentimentalvaliums',license:'CC BY-SA 3.0',source_url:'https://commons.wikimedia.org/wiki/File:G13_cannabis.jpg'},
  {name:'Jack Herer',image:'assets/featured/jack-herer.jpg',source:'Wikimedia contributor',license:'CC BY-SA 2.5',source_url:'https://commons.wikimedia.org/wiki/File:Jackherer.jpg'},
  {name:'Purple Haze',image:'assets/featured/purple-haze.jpg',source:'Mr TM',license:'CC BY-SA 3.0',source_url:'https://commons.wikimedia.org/wiki/File:Fleurs_coup%C3%A9es_de_Purple_Haze.JPG'},
  {name:'Super Silver Haze',image:'assets/featured/super-silver-haze.jpg',source:'Rikva',license:'Public domain',source_url:'https://commons.wikimedia.org/wiki/File:Super_silver_haze_trichomes.jpg'},
  {name:'White Widow',image:'assets/featured/white-widow.jpg',source:'Yuri Che',license:'CC BY-SA 3.0',source_url:'https://commons.wikimedia.org/wiki/File:White_Widow_(Green_House_Seeds)_01.jpg'},

  {name:'Afghan Kush',aliases:['Afghani Kush'],filename:'Afghani Kush.jpg',source:'Wikimedia Commons',license:'See file page',source_url:'https://commons.wikimedia.org/wiki/File:Afghani_Kush.jpg'},
  {name:"God's Gift",filename:'Gods Gift.jpg',source:'Wikimedia Commons',license:'See file page',source_url:'https://commons.wikimedia.org/wiki/File:Gods_Gift.jpg'},
  {name:'Green Crack',filename:'Green Crack.jpg',source:'Wikimedia Commons',license:'See file page',source_url:'https://commons.wikimedia.org/wiki/File:Green_Crack.jpg'},
  {name:'Jesus OG',filename:'Jesus OG 1e Hulp 01.jpg',source:'Wikimedia Commons',license:'See file page',source_url:'https://commons.wikimedia.org/wiki/File:Jesus_OG_1e_Hulp_01.jpg'},
  {name:'Kush',filename:'Kush close.jpg',source:'Wikimedia Commons',license:'See file page',source_url:'https://commons.wikimedia.org/wiki/File:Kush_close.jpg',exact_only:true},
  {name:'OG Kush',filename:'OG Kush.jpg',source:'Wikimedia Commons',license:'See file page',source_url:'https://commons.wikimedia.org/wiki/File:OG_Kush.jpg'},
  {name:'Lowryder',filename:'Female Lowryder.JPG',source:'Wikimedia Commons',license:'See file page',source_url:'https://commons.wikimedia.org/wiki/File:Female_Lowryder.JPG'},
  {name:'New York City Diesel',aliases:['NYC Diesel','NYC-Diesel'],filename:'Nycdiesel.jpg',source:'Wikimedia Commons',license:'See file page',source_url:'https://commons.wikimedia.org/wiki/File:Nycdiesel.jpg'},
  {name:'Northern Lights',aliases:['Northern Light'],filename:'Northern lights.JPG',source:'Wikimedia Commons',license:'See file page',source_url:'https://commons.wikimedia.org/wiki/File:Northern_lights.JPG'},
  {name:'Purple Goo',filename:'Purple Goo.jpg',source:'Wikimedia Commons',license:'See file page',source_url:'https://commons.wikimedia.org/wiki/File:Purple_Goo.jpg'},
  {name:'Purple Kush',filename:'Purple Kush.jpg',source:'Wikimedia Commons',license:'See file page',source_url:'https://commons.wikimedia.org/wiki/File:Purple_Kush.jpg'},
  {name:'Purple Urkle',aliases:['Purple Erkle'],filename:'Purple Erkle.jpg',source:'Wikimedia Commons',license:'See file page',source_url:'https://commons.wikimedia.org/wiki/File:Purple_Erkle.jpg'},
  {name:'Skywalker OG',filename:'Platinum Bubba and Skywalker OG.jpg',source:'Wikimedia Commons',license:'See file page',source_url:'https://commons.wikimedia.org/wiki/File:Platinum_Bubba_and_Skywalker_OG.jpg'},
  {name:'Trainwreck',filename:'Trainwreck Strain.jpg',source:'Wikimedia Commons',license:'See file page',source_url:'https://commons.wikimedia.org/wiki/File:Trainwreck_Strain.jpg'}
].map(item=>({
  ...item,
  image:item.image||`https://commons.wikimedia.org/wiki/Special:Redirect/file/${encodeURIComponent(item.filename)}?width=900`,
  kind:item.image?'bundled':'commons-direct'
}));
