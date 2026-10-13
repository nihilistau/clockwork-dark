// ui/tests/fixtures/creation.js -- READ RECEIPTS' creation form as GET /api/social/creation serves it
// (v0.22.0 T4's resolved_form()), RECORDED ONCE BY HAND from the shipped creation.yaml and population.yaml
// (v0.22.0 T27), never fetched by a test.

export const CREATION_FORM = {
  "fields": {
    "name": {
      "kind": "text",
      "max": 24,
      "default": "Sam"
    },
    "sex": {
      "kind": "choice",
      "of": [
        {
          "id": "male",
          "label": "male"
        },
        {
          "id": "female",
          "label": "female"
        }
      ],
      "default": "female"
    },
    "age": {
      "kind": "int",
      "min": 18,
      "max": 75,
      "default": 29
    },
    "neighbourhood": {
      "kind": "choice",
      "of_table": "neighbourhoods",
      "of": [
        {
          "id": "harbourside",
          "label": "Harbourside"
        },
        {
          "id": "old_town",
          "label": "Old Town"
        },
        {
          "id": "the_quays",
          "label": "The Quays"
        },
        {
          "id": "castle_hill",
          "label": "Castle Hill"
        },
        {
          "id": "the_lanes",
          "label": "The Lanes"
        },
        {
          "id": "riverside",
          "label": "Riverside"
        },
        {
          "id": "millbrook",
          "label": "Millbrook"
        },
        {
          "id": "northgate",
          "label": "Northgate"
        },
        {
          "id": "eastfield",
          "label": "Eastfield"
        },
        {
          "id": "saltmarsh",
          "label": "Saltmarsh"
        },
        {
          "id": "westcliff",
          "label": "Westcliff"
        }
      ]
    },
    "looking_for": {
      "kind": "choice",
      "of": [
        {
          "id": "friendship",
          "label": "friendship"
        },
        {
          "id": "short_term",
          "label": "short_term"
        },
        {
          "id": "long_term",
          "label": "long_term"
        },
        {
          "id": "unsure",
          "label": "unsure"
        }
      ],
      "default": "unsure"
    },
    "hobbies": {
      "kind": "multi",
      "of_table": "hobbies",
      "min": 2,
      "max": 6,
      "of": [
        {
          "id": "climbing",
          "label": "Climbing"
        },
        {
          "id": "hiking",
          "label": "Hiking"
        },
        {
          "id": "running",
          "label": "Running"
        },
        {
          "id": "cycling",
          "label": "Cycling"
        },
        {
          "id": "open_water_swimming",
          "label": "Sea swimming"
        },
        {
          "id": "surfing",
          "label": "Surfing"
        },
        {
          "id": "sailing",
          "label": "Sailing"
        },
        {
          "id": "paddleboarding",
          "label": "Paddleboarding"
        },
        {
          "id": "gym",
          "label": "The gym"
        },
        {
          "id": "yoga",
          "label": "Yoga"
        },
        {
          "id": "football",
          "label": "Five-a-side"
        },
        {
          "id": "tennis",
          "label": "Tennis"
        },
        {
          "id": "bouldering",
          "label": "Bouldering"
        },
        {
          "id": "dancing",
          "label": "Dancing"
        },
        {
          "id": "cooking",
          "label": "Cooking"
        },
        {
          "id": "baking",
          "label": "Baking"
        },
        {
          "id": "eating_out",
          "label": "Eating out"
        },
        {
          "id": "coffee",
          "label": "Good coffee"
        },
        {
          "id": "wine",
          "label": "Wine bars"
        },
        {
          "id": "craft_beer",
          "label": "Craft beer"
        },
        {
          "id": "gigs",
          "label": "Live music"
        },
        {
          "id": "clubbing",
          "label": "Clubbing"
        },
        {
          "id": "playing_guitar",
          "label": "Playing guitar"
        },
        {
          "id": "vinyl",
          "label": "Vinyl"
        },
        {
          "id": "karaoke",
          "label": "Karaoke"
        },
        {
          "id": "reading",
          "label": "Reading"
        },
        {
          "id": "writing",
          "label": "Writing"
        },
        {
          "id": "poetry",
          "label": "Poetry"
        },
        {
          "id": "film",
          "label": "Film"
        },
        {
          "id": "tv",
          "label": "Bingeing a series"
        },
        {
          "id": "video_games",
          "label": "Video games"
        },
        {
          "id": "board_games",
          "label": "Board games"
        },
        {
          "id": "pub_quizzes",
          "label": "Pub quizzes"
        },
        {
          "id": "chess",
          "label": "Chess"
        },
        {
          "id": "painting",
          "label": "Painting"
        },
        {
          "id": "photography",
          "label": "Photography"
        },
        {
          "id": "galleries",
          "label": "Galleries"
        },
        {
          "id": "theatre",
          "label": "Theatre"
        },
        {
          "id": "comedy",
          "label": "Stand-up comedy"
        },
        {
          "id": "museums",
          "label": "Museums"
        },
        {
          "id": "travel",
          "label": "Travel"
        },
        {
          "id": "languages",
          "label": "Learning languages"
        },
        {
          "id": "gardening",
          "label": "Gardening"
        },
        {
          "id": "plants",
          "label": "Houseplants"
        },
        {
          "id": "dogs",
          "label": "Dogs"
        },
        {
          "id": "cats",
          "label": "Cats"
        },
        {
          "id": "thrifting",
          "label": "Charity shops"
        },
        {
          "id": "fashion",
          "label": "Fashion"
        },
        {
          "id": "diy",
          "label": "DIY"
        },
        {
          "id": "volunteering",
          "label": "Volunteering"
        },
        {
          "id": "astronomy",
          "label": "Stargazing"
        },
        {
          "id": "podcasts",
          "label": "Podcasts"
        },
        {
          "id": "fishing",
          "label": "Fishing"
        }
      ]
    },
    "attributes": {
      "height": {
        "kind": "choice",
        "of": [
          {
            "id": "short",
            "label": "short"
          },
          {
            "id": "average",
            "label": "average"
          },
          {
            "id": "tall",
            "label": "tall"
          }
        ]
      },
      "build": {
        "kind": "choice",
        "of": [
          {
            "id": "slim",
            "label": "slim"
          },
          {
            "id": "average",
            "label": "average"
          },
          {
            "id": "athletic",
            "label": "athletic"
          },
          {
            "id": "curvy",
            "label": "curvy"
          },
          {
            "id": "broad",
            "label": "broad"
          },
          {
            "id": "heavy",
            "label": "heavy"
          }
        ]
      },
      "hair": {
        "kind": "choice",
        "of_table": "hair",
        "of": [
          {
            "id": "black_short",
            "label": "short black hair"
          },
          {
            "id": "black_long",
            "label": "long black hair"
          },
          {
            "id": "brown_short",
            "label": "short brown hair"
          },
          {
            "id": "brown_long",
            "label": "long brown hair"
          },
          {
            "id": "brown_curly",
            "label": "curly brown hair"
          },
          {
            "id": "blonde_short",
            "label": "short blonde hair"
          },
          {
            "id": "blonde_long",
            "label": "long blonde hair"
          },
          {
            "id": "red",
            "label": "red hair"
          },
          {
            "id": "auburn_wavy",
            "label": "wavy auburn hair"
          },
          {
            "id": "grey",
            "label": "grey hair"
          },
          {
            "id": "dyed",
            "label": "brightly dyed hair"
          },
          {
            "id": "shaved",
            "label": "a shaved head"
          },
          {
            "id": "braids",
            "label": "braids"
          },
          {
            "id": "afro",
            "label": "an afro"
          },
          {
            "id": "buzz_cut",
            "label": "a buzz cut"
          }
        ]
      },
      "style": {
        "kind": "choice",
        "of_table": "style",
        "of": [
          {
            "id": "casual",
            "label": "jeans-and-a-t-shirt casual"
          },
          {
            "id": "smart",
            "label": "smart"
          },
          {
            "id": "sporty",
            "label": "sporty"
          },
          {
            "id": "outdoorsy",
            "label": "outdoorsy"
          },
          {
            "id": "vintage",
            "label": "vintage"
          },
          {
            "id": "alternative",
            "label": "alternative"
          },
          {
            "id": "preppy",
            "label": "preppy"
          },
          {
            "id": "artsy",
            "label": "artsy"
          },
          {
            "id": "minimal",
            "label": "minimal"
          },
          {
            "id": "streetwear",
            "label": "streetwear"
          }
        ]
      },
      "job": {
        "kind": "choice",
        "of_table": "jobs",
        "of": [
          {
            "id": "nurse",
            "label": "Nurse"
          },
          {
            "id": "junior_doctor",
            "label": "Junior doctor"
          },
          {
            "id": "paramedic",
            "label": "Paramedic"
          },
          {
            "id": "pharmacist",
            "label": "Pharmacist"
          },
          {
            "id": "physio",
            "label": "Physiotherapist"
          },
          {
            "id": "dentist",
            "label": "Dentist"
          },
          {
            "id": "vet_nurse",
            "label": "Vet nurse"
          },
          {
            "id": "teacher",
            "label": "Teacher"
          },
          {
            "id": "lecturer",
            "label": "Lecturer"
          },
          {
            "id": "teaching_assistant",
            "label": "Teaching assistant"
          },
          {
            "id": "software_developer",
            "label": "Software developer"
          },
          {
            "id": "data_analyst",
            "label": "Data analyst"
          },
          {
            "id": "ux_designer",
            "label": "UX designer"
          },
          {
            "id": "graphic_designer",
            "label": "Graphic designer"
          },
          {
            "id": "architect",
            "label": "Architect"
          },
          {
            "id": "civil_engineer",
            "label": "Civil engineer"
          },
          {
            "id": "marine_engineer",
            "label": "Marine engineer"
          },
          {
            "id": "electrician",
            "label": "Electrician"
          },
          {
            "id": "plumber",
            "label": "Plumber"
          },
          {
            "id": "carpenter",
            "label": "Carpenter"
          },
          {
            "id": "mechanic",
            "label": "Mechanic"
          },
          {
            "id": "accountant",
            "label": "Accountant"
          },
          {
            "id": "solicitor",
            "label": "Solicitor"
          },
          {
            "id": "paralegal",
            "label": "Paralegal"
          },
          {
            "id": "hr_manager",
            "label": "HR manager"
          },
          {
            "id": "marketing_exec",
            "label": "Marketing exec"
          },
          {
            "id": "recruiter",
            "label": "Recruiter"
          },
          {
            "id": "estate_agent",
            "label": "Estate agent"
          },
          {
            "id": "journalist",
            "label": "Journalist"
          },
          {
            "id": "photographer",
            "label": "Photographer"
          },
          {
            "id": "musician",
            "label": "Musician"
          },
          {
            "id": "bartender",
            "label": "Bartender"
          },
          {
            "id": "chef",
            "label": "Chef"
          },
          {
            "id": "barista",
            "label": "Barista"
          },
          {
            "id": "baker",
            "label": "Baker"
          },
          {
            "id": "retail_manager",
            "label": "Retail manager"
          },
          {
            "id": "hairdresser",
            "label": "Hairdresser"
          },
          {
            "id": "personal_trainer",
            "label": "Personal trainer"
          },
          {
            "id": "police_officer",
            "label": "Police officer"
          },
          {
            "id": "firefighter",
            "label": "Firefighter"
          },
          {
            "id": "social_worker",
            "label": "Social worker"
          },
          {
            "id": "care_worker",
            "label": "Care worker"
          },
          {
            "id": "ferry_crew",
            "label": "Ferry deckhand"
          },
          {
            "id": "dock_worker",
            "label": "Dock worker"
          },
          {
            "id": "security_guard",
            "label": "Night security guard"
          },
          {
            "id": "delivery_driver",
            "label": "Delivery driver"
          },
          {
            "id": "museum_curator",
            "label": "Museum curator"
          },
          {
            "id": "librarian",
            "label": "Librarian"
          },
          {
            "id": "phd_student",
            "label": "PhD student"
          },
          {
            "id": "student",
            "label": "Student"
          },
          {
            "id": "small_business_owner",
            "label": "Small business owner"
          },
          {
            "id": "tattoo_artist",
            "label": "Tattoo artist"
          }
        ]
      },
      "drinks": {
        "kind": "choice",
        "of": [
          {
            "id": "never",
            "label": "never"
          },
          {
            "id": "socially",
            "label": "socially"
          },
          {
            "id": "often",
            "label": "often"
          }
        ]
      },
      "smokes": {
        "kind": "choice",
        "of": [
          {
            "id": "no",
            "label": "no"
          },
          {
            "id": "sometimes",
            "label": "sometimes"
          },
          {
            "id": "yes",
            "label": "yes"
          }
        ]
      },
      "kids": {
        "kind": "choice",
        "of": [
          {
            "id": "have",
            "label": "have"
          },
          {
            "id": "want",
            "label": "want"
          },
          {
            "id": "dont_want",
            "label": "dont_want"
          },
          {
            "id": "unsure",
            "label": "unsure"
          }
        ]
      }
    },
    "personality": {
      "kind": "sliders",
      "of": [
        "outgoing",
        "playful",
        "romantic",
        "adventurous",
        "homebody"
      ],
      "min": 1,
      "max": 5
    },
    "discovery": {
      "age_min": {
        "kind": "int",
        "min": 18,
        "default": 25
      },
      "age_max": {
        "kind": "int",
        "max": 75,
        "default": 38
      },
      "distance": {
        "kind": "choice",
        "of": [
          {
            "id": "near",
            "label": "near"
          },
          {
            "id": "city",
            "label": "city"
          },
          {
            "id": "anywhere",
            "label": "anywhere"
          }
        ],
        "default": "city"
      }
    },
    "photos": {
      "kind": "multi",
      "of_table": "photo_set",
      "min": 1,
      "max": 6,
      "of": [
        {
          "id": "hike_squint",
          "label": "on a hike, squinting at the camera"
        },
        {
          "id": "mirror_jacket",
          "label": "a mirror selfie in a good jacket"
        },
        {
          "id": "harbour_sunset",
          "label": "on the harbour wall at sunset"
        },
        {
          "id": "pint_laughing",
          "label": "laughing at a pub table"
        },
        {
          "id": "dog_cuddle",
          "label": "cuddling somebody's dog"
        },
        {
          "id": "wedding_guest",
          "label": "dressed up as a wedding guest"
        },
        {
          "id": "festival_crowd",
          "label": "in a festival crowd"
        },
        {
          "id": "kitchen_cooking",
          "label": "cooking, mid-stir"
        },
        {
          "id": "coffee_window",
          "label": "with a coffee by a café window"
        },
        {
          "id": "beach_windswept",
          "label": "windswept on a beach"
        },
        {
          "id": "gig_blurry",
          "label": "a blurry photo at a gig"
        },
        {
          "id": "bike_helmet",
          "label": "with a bike, helmet on"
        },
        {
          "id": "book_sofa",
          "label": "reading on a sofa"
        },
        {
          "id": "group_night_out",
          "label": "a group shot on a night out"
        },
        {
          "id": "travel_landmark",
          "label": "in front of a landmark abroad"
        },
        {
          "id": "gym_selfie",
          "label": "a post-gym selfie"
        },
        {
          "id": "climbing_wall",
          "label": "halfway up a climbing wall"
        },
        {
          "id": "boat_deck",
          "label": "on the deck of a small boat"
        },
        {
          "id": "snow_hat",
          "label": "in a woolly hat in the snow"
        },
        {
          "id": "art_gallery",
          "label": "looking at a painting in a gallery"
        },
        {
          "id": "garden_plants",
          "label": "among a lot of plants"
        },
        {
          "id": "cat_on_lap",
          "label": "with a cat on their lap"
        },
        {
          "id": "rooftop_drink",
          "label": "with a drink on a rooftop"
        },
        {
          "id": "market_stall",
          "label": "browsing a market stall"
        },
        {
          "id": "swim_cold",
          "label": "just out of a cold sea swim"
        },
        {
          "id": "costume_party",
          "label": "in a fancy-dress costume"
        },
        {
          "id": "graduation",
          "label": "in a graduation gown"
        },
        {
          "id": "car_selfie",
          "label": "a selfie in the driver's seat"
        },
        {
          "id": "kid_photo",
          "label": "a childhood photo, for fun"
        },
        {
          "id": "guitar_playing",
          "label": "playing guitar"
        },
        {
          "id": "picnic_blanket",
          "label": "on a picnic blanket"
        },
        {
          "id": "rain_umbrella",
          "label": "under an umbrella in the rain"
        },
        {
          "id": "candid_laugh",
          "label": "a candid shot, mid-laugh"
        }
      ]
    }
  }
};
